import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.models import CheckResult
from app.services.monitoring_service import MonitoringService
from app.workers.scheduler import MonitoringScheduler
from tests.conftest import Upstream, create_endpoint

API = "/api/v1"


def _jobs(scheduler: MonitoringScheduler) -> dict[str, timedelta]:
    return {
        job.id: job.trigger.interval for job in scheduler.scheduler.get_jobs() if job.id.startswith("check:")
    }


def test_reconcile_tracks_active_endpoints_without_duplicates(
    client: TestClient, auth: dict, monitor: MonitoringService
) -> None:
    a = create_endpoint(client, auth, interval_seconds=60)
    b = create_endpoint(client, auth, interval_seconds=120, is_active=False)
    scheduler = MonitoringScheduler(monitor, max_concurrency=2, reconcile_seconds=30)
    scheduler.scheduler.start(paused=True)  # real job store, but nothing actually fires

    scheduler.reconcile()
    scheduler.reconcile()  # idempotent: a restart / repeated reconcile never duplicates jobs
    assert _jobs(scheduler) == {f"check:{a['id']}": timedelta(seconds=60)}

    client.patch(f"{API}/endpoints/{b['id']}", json={"is_active": True}, headers=auth)
    client.patch(f"{API}/endpoints/{a['id']}", json={"interval_seconds": 300}, headers=auth)
    scheduler.reconcile()
    assert _jobs(scheduler) == {
        f"check:{a['id']}": timedelta(seconds=300),
        f"check:{b['id']}": timedelta(seconds=120),
    }

    client.patch(f"{API}/endpoints/{a['id']}", json={"is_active": False}, headers=auth)  # pause
    client.delete(f"{API}/endpoints/{b['id']}", headers=auth)
    scheduler.reconcile()
    assert _jobs(scheduler) == {}
    scheduler.shutdown()


def test_scheduled_check_records_result_and_skips_paused(
    client: TestClient, auth: dict, monitor: MonitoringService, upstream: Upstream, session_factory
) -> None:
    ep = create_endpoint(client, auth)
    upstream.json(ep["url"], {"ok": True})
    scheduler = MonitoringScheduler(monitor, max_concurrency=1, reconcile_seconds=30)
    scheduler.run_check(uuid.UUID(ep["id"]))
    with session_factory() as db:
        checks = db.scalars(select(CheckResult)).all()
    assert [(c.trigger, c.schema_status) for c in checks] == [("scheduled", "baseline_created")]

    client.patch(f"{API}/endpoints/{ep['id']}", json={"is_active": False}, headers=auth)
    scheduler.run_check(uuid.UUID(ep["id"]))
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CheckResult)) == 1

    scheduler.run_check(uuid.uuid4())  # deleted endpoint: logged, not raised


def test_reconcile_survives_database_outage(monitor: MonitoringService, monkeypatch) -> None:
    scheduler = MonitoringScheduler(monitor, max_concurrency=1, reconcile_seconds=30)

    def down():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(monitor, "session_factory", down)
    scheduler.reconcile()  # must not raise
    assert _jobs(scheduler) == {}
