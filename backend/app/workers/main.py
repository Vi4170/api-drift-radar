"""Worker entry point: `python -m app.workers.main`.

Only one worker may schedule checks at a time. A PostgreSQL advisory lock, held on a dedicated
connection for the life of the process, elects the active worker; extra replicas wait as
standbys and take over if the active one dies (its connection - and lock - go away).
"""

import logging
import signal
import threading

from pymongo.errors import PyMongoError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_document_store, get_monitoring_service
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.sql import get_engine
from app.workers.scheduler import MonitoringScheduler

logger = logging.getLogger("app.worker")

ADVISORY_LOCK_KEY = 0x44524946  # "DRIF"
RETRY_SECONDS = 10


def acquire_leadership(stop: threading.Event):
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        return None
    while not stop.is_set():
        try:
            conn = engine.connect()
            if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}).scalar():
                conn.commit()
                logger.info("Acquired scheduler leadership")
                return conn
            conn.close()
            logger.info("Another worker is active; standing by")
        except SQLAlchemyError as exc:
            logger.warning("Database not reachable (%s); retrying in %ss", type(exc).__name__, RETRY_SECONDS)
        stop.wait(RETRY_SECONDS)
    return None


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    leader_conn = acquire_leadership(stop)
    if stop.is_set():
        return
    try:
        get_document_store().ensure_indexes(settings.snapshot_retention_days)
    except PyMongoError as exc:  # Mongo may be down; checks then degrade to schema=unavailable
        logger.warning("Could not ensure MongoDB indexes (%s)", type(exc).__name__)

    scheduler = MonitoringScheduler(
        get_monitoring_service(), settings.monitor_max_concurrency, settings.worker_reconcile_seconds
    )
    scheduler.start()
    logger.info("Worker started (max concurrency %s)", settings.monitor_max_concurrency)
    try:
        while not stop.wait(RETRY_SECONDS):
            if leader_conn is not None:
                try:  # keep-alive; if the lock connection died, exit and let the orchestrator restart us
                    leader_conn.execute(text("SELECT 1"))
                except SQLAlchemyError:
                    logger.error("Lost the leadership connection; exiting")
                    break
    finally:
        scheduler.shutdown()
        if leader_conn is not None:
            leader_conn.close()
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
