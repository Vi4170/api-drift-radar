"""MonitoringScheduler: runs scheduled checks in a separate worker process.

* PostgreSQL is the source of truth. Jobs live in memory and are *reconciled* from the
  `endpoints` table every WORKER_RECONCILE_SECONDS: new/changed endpoints are (re)scheduled,
  paused or deleted ones removed. A restart therefore rebuilds the same job set - no duplicates.
* One job per endpoint (job id = endpoint id), max_instances=1 and coalesce=True: a slow check
  never overlaps with the next run of the same endpoint, and missed runs collapse into one.
* A bounded thread pool caps concurrent outbound requests (MONITOR_MAX_CONCURRENCY).
* Database outages: reconciliation keeps the current jobs and retries; failed checks are logged.
"""

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import NotFoundError
from app.models.enums import CheckTrigger
from app.repositories.endpoints import EndpointRepository
from app.services.monitoring_service import MonitoringService

logger = logging.getLogger(__name__)

JOB_PREFIX = "check:"


class MonitoringScheduler:
    def __init__(self, monitoring: MonitoringService, max_concurrency: int, reconcile_seconds: int):
        self.monitoring = monitoring
        self.reconcile_seconds = reconcile_seconds
        self.scheduler = BackgroundScheduler(
            executors={"default": ThreadPoolExecutor(max_concurrency)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120},
            timezone=UTC,
        )

    def start(self) -> None:
        self.scheduler.start()
        self.scheduler.add_job(
            self.reconcile,
            IntervalTrigger(seconds=self.reconcile_seconds),
            id="reconcile",
            next_run_time=datetime.now(UTC),
            replace_existing=True,
        )

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=True)

    def reconcile(self) -> None:
        try:
            with self.monitoring.session_factory() as db:
                wanted = {
                    f"{JOB_PREFIX}{eid}": interval
                    for eid, interval in EndpointRepository(db).active_schedule()
                }
        except SQLAlchemyError as exc:
            logger.warning(
                "Database unavailable during reconcile (%s); keeping current jobs", type(exc).__name__
            )
            return

        existing = {job.id: job for job in self.scheduler.get_jobs() if job.id.startswith(JOB_PREFIX)}
        for job_id in existing.keys() - wanted.keys():
            self.scheduler.remove_job(job_id)
            logger.info("Unscheduled %s", job_id)
        for job_id, interval in wanted.items():
            job = existing.get(job_id)
            if job is not None and job.trigger.interval == timedelta(seconds=interval):
                continue
            # Spread first runs so a restart does not fire every check at once.
            first_run = datetime.now(UTC) + timedelta(seconds=random.uniform(1, min(interval, 30)))
            self.scheduler.add_job(
                self.run_check,
                IntervalTrigger(seconds=interval, jitter=min(10, interval // 10)),
                id=job_id,
                args=[uuid.UUID(job_id.removeprefix(JOB_PREFIX))],
                next_run_time=first_run,
                replace_existing=True,
            )
            logger.info("Scheduled %s every %ss", job_id, interval)

    def run_check(self, endpoint_id: uuid.UUID) -> None:
        try:
            check = self.monitoring.run_check(endpoint_id, CheckTrigger.SCHEDULED)
            if check is not None:
                logger.info("Checked %s: %s (%s)", endpoint_id, check.outcome, check.schema_status)
        except NotFoundError:
            logger.info("Endpoint %s no longer exists; job will be removed", endpoint_id)
        except SQLAlchemyError as exc:
            logger.warning("Database error while checking %s: %s", endpoint_id, type(exc).__name__)
        except Exception:  # a single bad check must never kill the worker thread pool
            logger.exception("Unexpected error while checking %s", endpoint_id)
