"""Read-only views: schema comparison, metrics and the dashboard summary."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Endpoint, Incident
from app.models.enums import CheckOutcome, HealthStatus
from app.monitoring.schema_comparison import SchemaComparisonEngine
from app.repositories.documents import DocumentStore, DocumentStoreError
from app.repositories.endpoints import EndpointRepository
from app.repositories.incidents import IncidentRepository
from app.repositories.monitoring import BaselineRepository, CheckRepository
from app.schemas.dashboard import DashboardSummary, LatencyBucket, RecentCheckOut
from app.schemas.incident import IncidentDetail, IncidentEventOut, IncidentOut
from app.schemas.monitoring import (
    BaselineDetail,
    BaselineOut,
    CheckResultOut,
    LatencyPoint,
    MetricsOut,
    SchemaChangeOut,
    SchemaView,
)

MAX_SERIES_POINTS = 500
MAX_DASHBOARD_ROWS = 5000


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))
    return round(ordered[index], 2)


def incident_out(incident: Incident, endpoint_name: str) -> IncidentOut:
    return IncidentOut.model_validate(incident).model_copy(update={"endpoint_name": endpoint_name})


class ReportingService:
    def __init__(self, db: Session, docs: DocumentStore):
        self.db = db
        self.docs = docs
        self.endpoints = EndpointRepository(db)
        self.checks = CheckRepository(db)

    def _schema(self, endpoint_id: uuid.UUID, hash_: str | None) -> dict | None:
        if not hash_:
            return None
        try:
            return self.docs.get_schema(endpoint_id, hash_)
        except DocumentStoreError:
            return None

    def schema_view(self, owner_id: uuid.UUID, endpoint_id: uuid.UUID) -> SchemaView:
        endpoint = self.endpoints.get_owned(owner_id, endpoint_id)
        baseline = BaselineRepository(self.db).current(endpoint.id)
        baseline_schema = self._schema(endpoint.id, baseline.schema_hash) if baseline else None
        latest = self.checks.latest_schema_check(endpoint.id)
        latest_schema = self._schema(endpoint.id, latest.schema_hash) if latest else None

        changes: list[SchemaChangeOut] = []
        max_severity = None
        available = baseline_schema is not None and latest_schema is not None
        if available:
            diff = SchemaComparisonEngine().compare(baseline_schema, latest_schema)  # type: ignore[arg-type]
            changes = [SchemaChangeOut(**c.to_dict()) for c in diff.changes]
            max_severity = diff.max_severity
        return SchemaView(
            baseline=BaselineDetail(
                **BaselineOut.model_validate(baseline).model_dump(), json_schema=baseline_schema
            )
            if baseline
            else None,
            latest_schema_hash=latest.schema_hash if latest else None,
            latest_schema=latest_schema,
            latest_check_id=latest.id if latest else None,
            latest_checked_at=latest.checked_at if latest else None,
            latest_is_json=bool(latest and latest.outcome == CheckOutcome.SUCCESS_JSON),
            comparison_available=available,
            changes=changes,
            max_severity=max_severity,
        )

    def metrics(self, owner_id: uuid.UUID, endpoint_id: uuid.UUID, window_hours: int) -> MetricsOut:
        endpoint = self.endpoints.get_owned(owner_id, endpoint_id)
        since = datetime.now(UTC) - timedelta(hours=window_hours)
        total, healthy, avg = self.checks.stats([endpoint.id], since)
        recent = self.checks.window([endpoint.id], since, MAX_SERIES_POINTS)
        # ponytail: p95 is computed over the newest MAX_SERIES_POINTS checks, not the whole window;
        # use percentile_cont in PostgreSQL if exact long-window percentiles matter.
        latencies = [c.latency_ms for c in recent if c.latency_ms is not None]
        return MetricsOut(
            window_hours=window_hours,
            total_checks=total,
            healthy_checks=healthy,
            availability_percent=round(healthy / total * 100, 2) if total else None,
            avg_latency_ms=round(avg, 2) if avg is not None else None,
            p95_latency_ms=percentile(latencies, 95),
            series=[
                LatencyPoint(checked_at=c.checked_at, latency_ms=c.latency_ms, is_healthy=c.is_healthy)
                for c in reversed(recent)
            ],
        )

    def incident_detail(self, owner_id: uuid.UUID, incident_id: uuid.UUID) -> IncidentDetail:
        repo = IncidentRepository(self.db)
        incident, name = repo.get_owned(owner_id, incident_id)
        changes: list[SchemaChangeOut] = []
        available = False
        if incident.latest_diff_id:
            try:
                doc = self.docs.get_diff(incident.latest_diff_id)
            except DocumentStoreError:
                doc = None
            if doc is not None:
                changes = [SchemaChangeOut(**c) for c in doc["changes"]]
                available = True
        return IncidentDetail(
            **incident_out(incident, name).model_dump(),
            events=[IncidentEventOut.model_validate(e) for e in repo.events(incident.id)],
            changes=changes,
            changes_available=available,
        )

    def dashboard(self, owner_id: uuid.UUID) -> DashboardSummary:
        rows = self.db.execute(
            select(Endpoint.id, Endpoint.health_status, Endpoint.is_active).where(
                Endpoint.owner_id == owner_id
            )
        ).all()
        ids = [row.id for row in rows]
        health = {status.value: 0 for status in HealthStatus}
        for row in rows:
            health[row.health_status] = health.get(row.health_status, 0) + 1

        since = datetime.now(UTC) - timedelta(hours=24)
        total, healthy, avg = self.checks.stats(ids, since)
        incidents, _ = IncidentRepository(self.db).list_owned(owner_id, page=1, page_size=8)
        return DashboardSummary(
            total_endpoints=len(rows),
            active_endpoints=sum(1 for row in rows if row.is_active),
            healthy_endpoints=health[HealthStatus.HEALTHY],
            unhealthy_endpoints=health[HealthStatus.UNHEALTHY],
            unknown_endpoints=health[HealthStatus.UNKNOWN],
            endpoints_with_open_drift=self.endpoints.open_drift_endpoint_count(owner_id),
            open_incidents_by_severity=IncidentRepository(self.db).open_counts_by_severity(owner_id),
            checks_last_24h=total,
            availability_24h_percent=round(healthy / total * 100, 2) if total else None,
            avg_latency_24h_ms=round(avg, 2) if avg is not None else None,
            recent_incidents=[incident_out(i, name) for i, name in incidents],
            recent_checks=[
                RecentCheckOut(**CheckResultOut.model_validate(c).model_dump(), endpoint_name=name)
                for c, name in self.checks.recent_for_owner(owner_id, 10)
            ],
            latency_series=self._hourly(ids, since) if ids else [],
        )

    def _hourly(self, endpoint_ids: list[uuid.UUID], since: datetime) -> list[LatencyBucket]:
        # ponytail: buckets in Python over at most MAX_DASHBOARD_ROWS checks; switch to
        # date_trunc() GROUP BY in PostgreSQL when check volume grows past that.
        start = since.replace(minute=0, second=0, microsecond=0)
        buckets: dict[datetime, list] = {start + timedelta(hours=h): [0, 0, 0.0, 0] for h in range(25)}
        for check in self.checks.window(endpoint_ids, since, MAX_DASHBOARD_ROWS):
            key = check.checked_at.replace(minute=0, second=0, microsecond=0)
            if key not in buckets:
                continue
            bucket = buckets[key]
            bucket[0] += 1
            bucket[1] += int(check.is_healthy)
            if check.latency_ms is not None:
                bucket[2] += check.latency_ms
                bucket[3] += 1
        return [
            LatencyBucket(
                bucket_start=key,
                checks=b[0],
                healthy_checks=b[1],
                avg_latency_ms=round(b[2] / b[3], 2) if b[3] else None,
            )
            for key, b in sorted(buckets.items())
        ]
