"""Monitoring pipeline: classification, baseline lifecycle, drift detection, incidents."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError
from sqlalchemy import func, select

from app.models import Baseline, Incident, IncidentEvent
from app.repositories.documents import DocumentStore
from tests.conftest import Upstream, create_endpoint, run_check

API = "/api/v1"
URL = "https://api.example.com/users/1"
V1 = {"user_id": 101, "name": "Alex", "active": True}
V2 = {"user_id": "101", "active": True}


@pytest.fixture
def endpoint(client: TestClient, auth: dict) -> dict:
    return create_endpoint(client, auth, url=URL)


def _count(session_factory, model, **filters) -> int:
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(model).filter_by(**filters))


# ---- outcome classification ------------------------------------------------------------------


def test_first_json_response_creates_baseline(
    client: TestClient, auth: dict, endpoint: dict, upstream: Upstream
) -> None:
    upstream.json(URL, V1)
    check = run_check(client, auth, endpoint["id"])
    assert check["outcome"] == "success_json" and check["is_healthy"]
    assert check["schema_status"] == "baseline_created"
    assert check["snapshot_id"] == check["id"]

    ep = client.get(f"{API}/endpoints/{endpoint['id']}", headers=auth).json()
    assert ep["health_status"] == "healthy" and ep["schema_status"] == "baseline_created"
    assert ep["baseline_version"] == 1 and ep["last_status_code"] == 200

    view = client.get(f"{API}/endpoints/{endpoint['id']}/schema", headers=auth).json()
    assert view["baseline"]["version"] == 1 and view["baseline"]["approved_by_id"] is None
    assert view["baseline"]["json_schema"]["properties"]["user_id"]["type"] == "number"
    assert view["changes"] == [] and view["comparison_available"]


def test_unexpected_status_is_unhealthy_and_never_baselined(
    client, auth, endpoint, upstream, session_factory
) -> None:
    upstream.json(URL, {"error": "boom"}, status=500)
    check = run_check(client, auth, endpoint["id"])
    assert check["outcome"] == "unexpected_status" and not check["is_healthy"]
    assert check["schema_status"] == "not_applicable" and check["status_code"] == 500
    assert _count(session_factory, Baseline) == 0
    incidents = client.get(f"{API}/incidents", headers=auth).json()["items"]
    assert [(i["type"], i["severity"]) for i in incidents] == [("availability", "critical")]


def test_timeout_is_classified_and_retried_once(client, auth, endpoint, upstream) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    upstream.respond(URL, slow)
    check = run_check(client, auth, endpoint["id"])
    assert check["outcome"] == "timeout" and not check["is_healthy"]
    assert len(upstream.requests) == 2  # one bounded retry


def test_network_error(client, auth, endpoint, upstream) -> None:
    check = run_check(client, auth, endpoint["id"])  # no route registered -> ConnectError
    assert check["outcome"] == "network_error"
    assert "Connection failed" in check["error_message"]


def test_invalid_json(client, auth, endpoint, upstream) -> None:
    upstream.respond(
        URL, lambda r: httpx.Response(200, content=b"{not json", headers={"content-type": "application/json"})
    )
    check = run_check(client, auth, endpoint["id"])
    assert check["outcome"] == "invalid_json" and not check["is_healthy"]


def test_non_json_is_healthy_without_schema(client, auth, endpoint, upstream, session_factory) -> None:
    upstream.respond(
        URL, lambda r: httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})
    )
    check = run_check(client, auth, endpoint["id"])
    assert check["outcome"] == "success_non_json" and check["is_healthy"]
    assert check["schema_status"] == "not_applicable"
    assert _count(session_factory, Baseline) == 0


def test_json_without_json_content_type_is_sniffed(client, auth, endpoint, upstream) -> None:
    upstream.respond(
        URL, lambda r: httpx.Response(200, text='{"a": 1}', headers={"content-type": "text/plain"})
    )
    assert run_check(client, auth, endpoint["id"])["outcome"] == "success_json"


def test_monitor_sends_only_configured_headers(client, auth, upstream) -> None:
    ep = create_endpoint(client, auth, url=URL, headers={"X-Api-Key": "k-123"})
    upstream.json(URL, V1)
    run_check(client, auth, ep["id"])
    sent = upstream.requests[-1].headers
    assert sent["x-api-key"] == "k-123"
    assert "authorization" not in sent and "cookie" not in sent
    assert sent["user-agent"].startswith("APIDriftRadar")


def test_expected_status_can_be_non_200(client, auth, upstream) -> None:
    ep = create_endpoint(client, auth, url=URL, expected_status=202)
    upstream.json(URL, V1, status=202)
    assert run_check(client, auth, ep["id"])["is_healthy"]


# ---- drift, baseline preservation, incidents ---------------------------------------------------


def test_drift_detected_baseline_preserved_and_incident_deduplicated(
    client,
    auth,
    endpoint,
    upstream,
    session_factory,
) -> None:
    upstream.json(URL, V1)
    run_check(client, auth, endpoint["id"])
    baseline_before = client.get(f"{API}/endpoints/{endpoint['id']}/schema", headers=auth).json()["baseline"]

    upstream.json(URL, V2)
    drift = run_check(client, auth, endpoint["id"])
    assert drift["schema_status"] == "drifted" and drift["drift_severity"] == "critical"
    assert drift["change_count"] == 2 and drift["is_healthy"]  # healthy HTTP, incompatible schema

    view = client.get(f"{API}/endpoints/{endpoint['id']}/schema", headers=auth).json()
    assert view["baseline"]["schema_hash"] == baseline_before["schema_hash"]  # baseline untouched
    assert {(c["path"], c["kind"]) for c in view["changes"]} == {
        ("$.user_id", "type_changed"),
        ("$.name", "field_removed"),
    }

    for _ in range(3):  # same drift polled repeatedly
        run_check(client, auth, endpoint["id"])
    incidents = client.get(f"{API}/incidents", params={"type": "schema_drift"}, headers=auth).json()
    assert incidents["total"] == 1
    incident = incidents["items"][0]
    assert incident["occurrence_count"] == 4 and incident["status"] == "open"
    assert _count(session_factory, IncidentEvent) == 1  # only "opened"; repeats don't spam history
    assert _count(session_factory, Baseline) == 1

    detail = client.get(f"{API}/incidents/{incident['id']}", headers=auth).json()
    assert detail["changes_available"] and len(detail["changes"]) == 2
    assert detail["events"][0]["event_type"] == "opened"


def test_changed_drift_updates_same_incident(client, auth, endpoint, upstream, session_factory) -> None:
    upstream.json(URL, V1)
    run_check(client, auth, endpoint["id"])
    upstream.json(URL, {**V1, "extra": 1})
    first = run_check(client, auth, endpoint["id"])
    assert first["drift_severity"] == "info"
    upstream.json(URL, V2)
    second = run_check(client, auth, endpoint["id"])
    assert first["incident_id"] == second["incident_id"]
    detail = client.get(f"{API}/incidents/{second['incident_id']}", headers=auth).json()
    assert detail["severity"] == "critical"
    assert [e["event_type"] for e in detail["events"]] == ["opened", "changed"]


def test_drift_auto_resolves_when_response_recovers(client, auth, endpoint, upstream) -> None:
    upstream.json(URL, V1)
    run_check(client, auth, endpoint["id"])
    upstream.json(URL, V2)
    drift = run_check(client, auth, endpoint["id"])
    upstream.json(URL, {"user_id": 5, "name": "Sam", "active": False})  # same shape as baseline
    ok = run_check(client, auth, endpoint["id"])
    assert ok["schema_status"] == "compatible"
    incident = client.get(f"{API}/incidents/{drift['incident_id']}", headers=auth).json()
    assert incident["status"] == "resolved" and incident["resolution"] == "auto_recovered"


def test_failed_check_does_not_touch_baseline_or_schema_status(client, auth, endpoint, upstream) -> None:
    upstream.json(URL, V1)
    run_check(client, auth, endpoint["id"])
    upstream.json(URL, {"oops": True}, status=503)
    run_check(client, auth, endpoint["id"])
    ep = client.get(f"{API}/endpoints/{endpoint['id']}", headers=auth).json()
    assert ep["health_status"] == "unhealthy"
    assert ep["schema_status"] == "baseline_created"  # last *schema* result is kept
    assert ep["baseline_version"] == 1


def test_response_no_longer_json_is_structure_drift(client, auth, endpoint, upstream) -> None:
    upstream.json(URL, V1)
    run_check(client, auth, endpoint["id"])
    upstream.respond(
        URL, lambda r: httpx.Response(200, text="maintenance", headers={"content-type": "text/plain"})
    )
    check = run_check(client, auth, endpoint["id"])
    assert check["schema_status"] == "drifted" and check["drift_severity"] == "critical"
    view = client.get(f"{API}/endpoints/{endpoint['id']}/schema", headers=auth).json()
    assert view["changes"][0]["kind"] == "response_structure_changed"
    assert view["latest_is_json"] is False


def test_accept_new_baseline_requires_explicit_action(client, auth, endpoint, upstream) -> None:
    upstream.json(URL, V1)
    first = run_check(client, auth, endpoint["id"])
    upstream.json(URL, V2)
    drift = run_check(client, auth, endpoint["id"])
    base = f"{API}/endpoints/{endpoint['id']}"

    # Validation: unknown check, failed check, already-current schema
    assert client.post(f"{base}/baseline", json={"check_id": endpoint["id"]}, headers=auth).status_code == 404
    assert client.post(f"{base}/baseline", json={"check_id": first["id"]}, headers=auth).status_code == 409
    upstream.json(URL, {}, status=500)
    failed = run_check(client, auth, endpoint["id"])
    assert client.post(f"{base}/baseline", json={"check_id": failed["id"]}, headers=auth).status_code == 422
    assert client.post(f"{base}/baseline", json={}, headers=auth).status_code == 422

    accepted = client.post(f"{base}/baseline", json={"check_id": drift["id"]}, headers=auth)
    assert accepted.status_code == 201
    assert accepted.json()["version"] == 2 and accepted.json()["approved_by_id"] is not None

    history = client.get(f"{base}/baselines", headers=auth).json()
    assert [(b["version"], b["is_current"]) for b in history] == [(2, True), (1, False)]
    incident = client.get(f"{API}/incidents/{drift['incident_id']}", headers=auth).json()
    assert incident["status"] == "resolved" and incident["resolution"] == "baseline_accepted"
    assert incident["events"][-1]["message"] == "New baseline v2 accepted"

    upstream.json(URL, V2)
    assert run_check(client, auth, endpoint["id"])["schema_status"] == "compatible"


def test_manual_resolution(client, auth, endpoint, upstream) -> None:
    upstream.json(URL, {}, status=500)
    check = run_check(client, auth, endpoint["id"])
    url = f"{API}/incidents/{check['incident_id']}/resolve"
    resolved = client.post(url, json={"note": "Upstream deploy rolled back"}, headers=auth)
    assert resolved.status_code == 200 and resolved.json()["resolution"] == "manual"
    assert resolved.json()["events"][-1]["message"] == "Upstream deploy rolled back"
    assert client.post(url, json={}, headers=auth).status_code == 409


def test_availability_incident_auto_resolves(client, auth, endpoint, upstream) -> None:
    upstream.json(URL, {}, status=500)
    failed = run_check(client, auth, endpoint["id"])
    upstream.json(URL, V1)
    run_check(client, auth, endpoint["id"])
    incident = client.get(f"{API}/incidents/{failed['incident_id']}", headers=auth).json()
    assert incident["status"] == "resolved" and incident["resolution"] == "auto_recovered"


def test_incident_filters_and_cross_user_isolation(client, auth, endpoint, upstream) -> None:
    from tests.conftest import register

    upstream.json(URL, {}, status=500)
    check = run_check(client, auth, endpoint["id"])
    params = {"status": "open", "severity": "critical", "type": "availability", "endpoint_id": endpoint["id"]}
    assert client.get(f"{API}/incidents", params=params, headers=auth).json()["total"] == 1
    assert client.get(f"{API}/incidents", params={"severity": "info"}, headers=auth).json()["total"] == 0
    assert client.get(f"{API}/incidents", params={"status": "resolved"}, headers=auth).json()["total"] == 0

    other = register(client)
    assert client.get(f"{API}/incidents", headers=other).json()["total"] == 0
    assert client.get(f"{API}/incidents/{check['incident_id']}", headers=other).status_code == 404
    assert (
        client.post(f"{API}/incidents/{check['incident_id']}/resolve", json={}, headers=other).status_code
        == 404
    )


# ---- cross-database failure handling -----------------------------------------------------------


class _BrokenCollection:
    def __getattr__(self, name: str):
        def fail(*args: object, **kwargs: object) -> None:
            raise ServerSelectionTimeoutError("mongo down")

        return fail


class _BrokenDb:
    def __getattr__(self, name: str) -> _BrokenCollection:
        return _BrokenCollection()

    def command(self, *args: object) -> None:
        raise ServerSelectionTimeoutError("mongo down")


def test_document_store_outage_never_creates_or_changes_baseline(
    client,
    auth,
    endpoint,
    upstream,
    monitor,
    session_factory,
    docs,
) -> None:
    upstream.json(URL, V1)
    run_check(client, auth, endpoint["id"])
    monitor.docs = DocumentStore(_BrokenDb())  # MongoDB goes away

    upstream.json(URL, V2)
    check = run_check(client, auth, endpoint["id"])
    assert check["schema_status"] == "unavailable"  # not "compatible": we could not compare
    assert check["is_healthy"] and check["snapshot_id"] is None
    assert _count(session_factory, Incident, type="schema_drift") == 0
    with session_factory() as db:
        assert db.scalar(select(Baseline.version).where(Baseline.is_current.is_(True))) == 1

    monitor.docs = docs  # recovers: the preserved baseline still catches the drift
    assert run_check(client, auth, endpoint["id"])["schema_status"] == "drifted"


def test_document_store_outage_on_first_check_creates_no_baseline(
    client, auth, endpoint, upstream, monitor, session_factory
) -> None:
    monitor.docs = DocumentStore(_BrokenDb())
    upstream.json(URL, V1)
    assert run_check(client, auth, endpoint["id"])["schema_status"] == "not_applicable"
    assert _count(session_factory, Baseline) == 0


def test_delete_cleans_up_sql_and_documents(
    client, auth, endpoint, upstream, session_factory, mongo_db
) -> None:
    upstream.json(URL, V1)
    run_check(client, auth, endpoint["id"])
    upstream.json(URL, V2)
    run_check(client, auth, endpoint["id"])
    assert mongo_db.snapshots.count_documents({}) == 2

    assert client.delete(f"{API}/endpoints/{endpoint['id']}", headers=auth).status_code == 204
    assert _count(session_factory, Baseline) == 0 and _count(session_factory, Incident) == 0
    for name in ("snapshots", "schemas", "diffs"):
        assert mongo_db[name].count_documents({}) == 0


def test_metrics_and_history(client, auth, endpoint, upstream) -> None:
    upstream.json(URL, V1)
    for _ in range(3):
        run_check(client, auth, endpoint["id"])
    upstream.json(URL, {}, status=500)
    run_check(client, auth, endpoint["id"])

    metrics = client.get(f"{API}/endpoints/{endpoint['id']}/metrics", headers=auth).json()
    assert metrics["total_checks"] == 4 and metrics["healthy_checks"] == 3
    assert metrics["availability_percent"] == 75.0 and len(metrics["series"]) == 4

    history = client.get(
        f"{API}/endpoints/{endpoint['id']}/checks", params={"page_size": 2}, headers=auth
    ).json()
    assert history["total"] == 4 and len(history["items"]) == 2
    assert history["items"][0]["outcome"] == "unexpected_status"  # newest first
    unhealthy = client.get(
        f"{API}/endpoints/{endpoint['id']}/checks", params={"healthy": False}, headers=auth
    )
    assert unhealthy.json()["total"] == 1

    summary = client.get(f"{API}/dashboard/summary", headers=auth).json()
    assert summary["total_endpoints"] == 1 and summary["unhealthy_endpoints"] == 1
    assert summary["checks_last_24h"] == 4 and summary["availability_24h_percent"] == 75.0
    assert summary["open_incidents_by_severity"] == {"critical": 1}
    assert (
        len(summary["recent_checks"]) == 4
        and summary["recent_checks"][0]["endpoint_name"] == endpoint["name"]
    )
    assert sum(b["checks"] for b in summary["latency_series"]) == 4


def test_manual_check_cooldown(client, auth, endpoint, upstream, monkeypatch) -> None:
    from app.api import deps

    upstream.json(URL, V1)
    run_check(client, auth, endpoint["id"])
    monkeypatch.setenv("MANUAL_CHECK_COOLDOWN_SECONDS", "60")
    deps.get_settings.cache_clear()
    response = client.post(f"{API}/endpoints/{endpoint['id']}/checks", headers=auth)
    assert response.status_code == 429
