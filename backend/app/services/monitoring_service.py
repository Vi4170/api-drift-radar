"""MonitoringService: one complete check of one endpoint, shared by the API and the worker.

Pipeline:  load config -> fetch (no DB locks held) -> classify -> infer schema
           -> write schema/snapshot documents (MongoDB, idempotent)
           -> one PostgreSQL transaction holding the endpoint row lock:
              compare with the current baseline, create the initial baseline if none,
              record diff + incidents + check result + endpoint summary.

Cross-database consistency: MongoDB documents are written first and are content-addressed, so
PostgreSQL never references a document that does not exist. If the SQL transaction fails, the
snapshot just written is deleted (best effort; otherwise it expires via TTL). If MongoDB is down,
the check is still recorded with schema_status=unavailable and the baseline is never touched.
"""

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import Baseline, CheckResult, Endpoint, Incident
from app.models.enums import CheckOutcome, CheckTrigger, HealthStatus, SchemaStatus
from app.monitoring.http_client import FetchResult, SafeHTTPClient
from app.monitoring.schema_comparison import SchemaComparisonEngine, SchemaDiff
from app.monitoring.schema_inference import SchemaInferenceEngine, SchemaNode
from app.repositories.documents import DocumentStore, DocumentStoreError
from app.repositories.endpoints import EndpointRepository
from app.repositories.monitoring import BaselineRepository
from app.services.baseline_service import BaselineService
from app.services.incident_service import IncidentService

logger = logging.getLogger(__name__)

# Schema recorded for a valid non-JSON response, so "API stopped returning JSON" is detected
# as a top-level structure change against an existing JSON baseline.
NON_JSON_SCHEMA: SchemaNode = {"type": "non_json", "nullable": False}


@dataclass
class Evaluation:
    outcome: CheckOutcome
    is_healthy: bool
    error: str | None = None
    body: Any = None
    schema: SchemaNode | None = None


@dataclass
class _EndpointConfig:
    url: str
    headers: dict[str, str]
    timeout: float
    expected_status: int


def _looks_like_json(content_type: str | None, body: bytes) -> tuple[bool, bool]:
    """(declared_json, sniffable_json)"""
    media = (content_type or "").split(";")[0].strip().lower()
    declared = media == "application/json" or media.endswith("+json")
    return declared, body.lstrip()[:1] in (b"{", b"[")


class MonitoringService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        http: SafeHTTPClient,
        docs: DocumentStore,
        inference: SchemaInferenceEngine | None = None,
        comparison: SchemaComparisonEngine | None = None,
    ):
        self.session_factory = session_factory
        self.http = http
        self.docs = docs
        self.inference = inference or SchemaInferenceEngine()
        self.comparison = comparison or SchemaComparisonEngine()

    # ---- classification -------------------------------------------------------------------
    def evaluate(self, fetch: FetchResult, expected_status: int) -> Evaluation:
        if fetch.outcome is not None:
            return Evaluation(fetch.outcome, False, fetch.error)
        if fetch.status_code != expected_status:
            return Evaluation(
                CheckOutcome.UNEXPECTED_STATUS,
                False,
                f"Expected HTTP {expected_status}, got {fetch.status_code}",
            )
        body = fetch.body or b""
        declared, sniffable = _looks_like_json(fetch.content_type, body)
        if declared or sniffable:
            try:
                parsed = json.loads(body)
                return Evaluation(
                    CheckOutcome.SUCCESS_JSON, True, body=parsed, schema=self.inference.infer(parsed)
                )
            except (ValueError, UnicodeDecodeError, RecursionError):
                if declared:
                    return Evaluation(
                        CheckOutcome.INVALID_JSON, False, "Response declared JSON but could not be parsed"
                    )
        return Evaluation(CheckOutcome.SUCCESS_NON_JSON, True, schema=NON_JSON_SCHEMA)

    # ---- pipeline -------------------------------------------------------------------------
    def run_check(self, endpoint_id: uuid.UUID, trigger: CheckTrigger) -> CheckResult | None:
        """Run one check. Returns None if a scheduled check finds the endpoint paused."""
        with self.session_factory() as db:
            endpoint = db.get(Endpoint, endpoint_id)
            if endpoint is None:
                raise NotFoundError("Endpoint not found")
            if trigger == CheckTrigger.SCHEDULED and not endpoint.is_active:
                return None
            config = _EndpointConfig(
                endpoint.url, dict(endpoint.headers or {}), endpoint.timeout_seconds, endpoint.expected_status
            )

        fetch = self.http.get(config.url, config.headers, config.timeout)
        evaluation = self.evaluate(fetch, config.expected_status)
        check_id = uuid.uuid4()

        observed_hash: str | None = None
        snapshot_id: str | None = None
        if evaluation.schema is not None:
            try:
                observed_hash = self.docs.save_schema(endpoint_id, evaluation.schema)
                if evaluation.outcome == CheckOutcome.SUCCESS_JSON:
                    snapshot_id = self.docs.save_snapshot(
                        check_id, endpoint_id, evaluation.body, fetch.status_code or 0, observed_hash
                    )
            except DocumentStoreError:
                logger.warning("Document store unavailable; recording check %s without schema data", check_id)

        try:
            return self._record(endpoint_id, check_id, trigger, fetch, evaluation, observed_hash, snapshot_id)
        except Exception:
            if snapshot_id:
                try:
                    self.docs.delete_snapshot(snapshot_id)
                except DocumentStoreError:
                    logger.warning("Orphaned snapshot %s left behind (expires via TTL)", snapshot_id)
            raise

    def _record(
        self,
        endpoint_id: uuid.UUID,
        check_id: uuid.UUID,
        trigger: CheckTrigger,
        fetch: FetchResult,
        evaluation: Evaluation,
        observed_hash: str | None,
        snapshot_id: str | None,
    ) -> CheckResult:
        now = datetime.now(UTC)
        with self.session_factory() as db:
            endpoint = EndpointRepository(db).get_for_update(endpoint_id)
            if endpoint is None:
                raise NotFoundError("Endpoint was deleted during the check")
            check = CheckResult(
                id=check_id,
                endpoint_id=endpoint.id,
                checked_at=now,
                trigger=trigger,
                outcome=evaluation.outcome,
                is_healthy=evaluation.is_healthy,
                status_code=fetch.status_code,
                latency_ms=fetch.latency_ms,
                response_size_bytes=fetch.size_bytes,
                content_type=(fetch.content_type or None) and fetch.content_type[:255],
                error_message=evaluation.error and evaluation.error[:500],
                schema_status=SchemaStatus.NOT_APPLICABLE,
                schema_hash=observed_hash,
                change_count=0,
                snapshot_id=snapshot_id,
            )
            db.add(check)
            db.flush()

            incidents = IncidentService(db)
            drift_incident = None
            if evaluation.schema is not None:
                drift_incident = self._apply_schema(db, endpoint, check, evaluation, observed_hash, now)
            availability_incident = incidents.record_availability(endpoint, check, now)
            linked = drift_incident or availability_incident
            check.incident_id = linked.id if linked else None

            endpoint.last_checked_at = now
            endpoint.last_outcome = check.outcome
            endpoint.last_status_code = check.status_code
            endpoint.last_latency_ms = check.latency_ms
            endpoint.health_status = HealthStatus.HEALTHY if check.is_healthy else HealthStatus.UNHEALTHY
            if check.schema_status != SchemaStatus.NOT_APPLICABLE:
                endpoint.schema_status = check.schema_status
                endpoint.schema_checked_at = now
                if observed_hash:
                    endpoint.latest_schema_hash = observed_hash
            db.commit()
            return check

    def _apply_schema(
        self,
        db: Session,
        endpoint: Endpoint,
        check: CheckResult,
        evaluation: Evaluation,
        observed_hash: str | None,
        now: datetime,
    ) -> Incident | None:
        """Compare against the approved baseline; returns the drift incident if one is open."""
        baseline = BaselineRepository(db).current(endpoint.id)
        is_json = evaluation.outcome == CheckOutcome.SUCCESS_JSON
        if baseline is None:
            if is_json and observed_hash:
                baseline = BaselineService(db, self.docs).create_initial(
                    endpoint, observed_hash, check.id, now
                )
                check.baseline_id = baseline.id
                check.schema_status = SchemaStatus.BASELINE_CREATED
            # non-JSON with no baseline: nothing to compare (stays not_applicable)
            return None

        check.baseline_id = baseline.id
        if observed_hash is None:
            check.schema_status = SchemaStatus.UNAVAILABLE
            return None
        if observed_hash == baseline.schema_hash:
            check.schema_status = SchemaStatus.COMPATIBLE
            IncidentService(db).clear_drift(endpoint, "auto_recovered", now)
            return None

        diff = self._diff(endpoint, baseline, evaluation.schema)
        if diff is None:
            check.schema_status = SchemaStatus.UNAVAILABLE
            return None
        if not diff.has_drift:  # e.g. a type narrowed: different hash but nothing breaking
            check.schema_status = SchemaStatus.COMPATIBLE
            IncidentService(db).clear_drift(endpoint, "auto_recovered", now)
            return None

        diff_id = None
        try:
            diff_id = self.docs.save_diff(
                endpoint.id,
                baseline.schema_hash,
                observed_hash,
                [c.to_dict() for c in diff.changes],
                diff.counts(),
            )
        except DocumentStoreError:
            logger.warning("Could not store diff document for check %s", check.id)
        check.schema_status = SchemaStatus.DRIFTED
        check.drift_severity = diff.max_severity
        check.change_count = len(diff.changes)
        check.diff_id = diff_id
        return IncidentService(db).record_drift(endpoint, baseline, observed_hash, diff, diff_id, now)

    def _diff(self, endpoint: Endpoint, baseline: Baseline, observed: SchemaNode | None) -> SchemaDiff | None:
        try:
            baseline_schema = self.docs.get_schema(endpoint.id, baseline.schema_hash)
        except DocumentStoreError:
            logger.warning("Baseline schema for endpoint %s unavailable", endpoint.id)
            return None
        if baseline_schema is None or observed is None:
            return None
        return self.comparison.compare(baseline_schema, observed)
