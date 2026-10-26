"""Incident lifecycle: open, deduplicate, update and resolve.

Rules:
  * At most one OPEN incident per (endpoint, type) - also enforced by a partial unique index.
  * The same drift observed again (same baseline + same observed schema hash) only bumps
    `occurrence_count` / `last_seen_at`; no new incident and no new history event.
  * A *different* drift updates the open incident and records a `changed` event.
  * Drift incidents resolve when the response matches the baseline again (`auto_recovered`)
    or when a new baseline is accepted (`baseline_accepted`); availability incidents resolve
    on the next healthy check. Users can also resolve manually.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import Baseline, CheckResult, Endpoint, Incident, IncidentEvent
from app.models.enums import CheckOutcome, IncidentStatus, IncidentType, Severity
from app.monitoring.schema_comparison import SchemaDiff
from app.repositories.incidents import IncidentRepository


def summarize_diff(diff: SchemaDiff, limit: int = 1000) -> str:
    counts = diff.counts()
    head = f"{len(diff.changes)} schema change(s): " + ", ".join(f"{n} {s}" for s, n in counts.items() if n)
    details = "; ".join(f"{c.path} {c.kind.value}" for c in diff.changes[:8])
    more = f"; +{len(diff.changes) - 8} more" if len(diff.changes) > 8 else ""
    return f"{head}. {details}{more}"[:limit]


def availability_severity(outcome: str, status_code: int | None) -> Severity:
    if outcome in (CheckOutcome.TIMEOUT, CheckOutcome.NETWORK_ERROR, CheckOutcome.BLOCKED):
        return Severity.CRITICAL
    if outcome == CheckOutcome.UNEXPECTED_STATUS and (status_code or 0) >= 500:
        return Severity.CRITICAL
    return Severity.WARNING


class IncidentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IncidentRepository(db)

    def _event(
        self,
        incident: Incident,
        event_type: str,
        message: str,
        now: datetime,
        actor_id: uuid.UUID | None = None,
        **details: Any,
    ) -> None:
        self.db.add(
            IncidentEvent(
                incident_id=incident.id,
                event_type=event_type,
                message=message,
                actor_id=actor_id,
                details=details,
                created_at=now,
            )
        )

    def record_drift(
        self,
        endpoint: Endpoint,
        baseline: Baseline,
        observed_hash: str,
        diff: SchemaDiff,
        diff_id: str | None,
        now: datetime,
    ) -> Incident:
        severity = diff.max_severity or Severity.INFO
        summary = summarize_diff(diff)
        incident = self.repo.get_open(endpoint.id, IncidentType.SCHEMA_DRIFT)
        if incident is None:
            incident = Incident(
                id=uuid.uuid4(),
                endpoint_id=endpoint.id,
                type=IncidentType.SCHEMA_DRIFT,
                status=IncidentStatus.OPEN,
                severity=severity,
                title=f"Schema drift detected on {endpoint.name}",
                summary=summary,
                fingerprint=observed_hash,
                baseline_id=baseline.id,
                latest_diff_id=diff_id,
                occurrence_count=1,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.db.add(incident)
            self.db.flush()  # incident row must exist before its events reference it
            self._event(
                incident, "opened", summary, now, counts=diff.counts(), baseline_version=baseline.version
            )
            return incident

        incident.last_seen_at = now
        incident.occurrence_count += 1
        if incident.fingerprint != observed_hash or incident.baseline_id != baseline.id:
            incident.fingerprint = observed_hash
            incident.baseline_id = baseline.id
            incident.latest_diff_id = diff_id
            incident.severity = severity
            incident.summary = summary
            self._event(
                incident, "changed", f"Observed schema changed again. {summary}", now, counts=diff.counts()
            )
        return incident

    def clear_drift(
        self,
        endpoint: Endpoint,
        resolution: str,
        now: datetime,
        actor_id: uuid.UUID | None = None,
        message: str | None = None,
    ) -> Incident | None:
        incident = self.repo.get_open(endpoint.id, IncidentType.SCHEMA_DRIFT)
        if incident is not None:
            text = message or "Response matches the approved baseline again"
            self._resolve(incident, resolution, now, actor_id, text)
        return incident

    def record_availability(self, endpoint: Endpoint, check: CheckResult, now: datetime) -> Incident | None:
        incident = self.repo.get_open(endpoint.id, IncidentType.AVAILABILITY)
        if check.is_healthy:
            if incident is not None:
                self._resolve(incident, "auto_recovered", now, None, "Endpoint is healthy again")
            return None
        severity = availability_severity(check.outcome, check.status_code)
        reason = check.error_message or f"HTTP {check.status_code}"
        if incident is None:
            incident = Incident(
                id=uuid.uuid4(),
                endpoint_id=endpoint.id,
                type=IncidentType.AVAILABILITY,
                status=IncidentStatus.OPEN,
                severity=severity,
                title=f"{endpoint.name} is unhealthy",
                summary=f"{check.outcome}: {reason}"[:1000],
                fingerprint=check.outcome,
                occurrence_count=1,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.db.add(incident)
            self.db.flush()  # incident row must exist before its events reference it
            self._event(incident, "opened", incident.summary, now, outcome=check.outcome)
            return incident
        incident.last_seen_at = now
        incident.occurrence_count += 1
        if incident.fingerprint != check.outcome:
            incident.fingerprint = check.outcome
            incident.severity = severity
            incident.summary = f"{check.outcome}: {reason}"[:1000]
            self._event(incident, "changed", incident.summary, now, outcome=check.outcome)
        return incident

    def resolve_manually(self, incident: Incident, actor_id: uuid.UUID, note: str, now: datetime) -> None:
        if incident.status != IncidentStatus.OPEN:
            raise ConflictError("Incident is already resolved")
        self._resolve(incident, "manual", now, actor_id, note or "Resolved manually")

    def _resolve(
        self, incident: Incident, resolution: str, now: datetime, actor_id: uuid.UUID | None, message: str
    ) -> None:
        incident.status = IncidentStatus.RESOLVED
        incident.resolution = resolution
        incident.resolved_at = now
        incident.resolved_by_id = actor_id
        self._event(incident, "resolved", message, now, actor_id, resolution=resolution)
