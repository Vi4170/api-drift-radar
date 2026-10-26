import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel, StrictModel


class CheckResultOut(ORMModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    checked_at: datetime
    trigger: str
    outcome: str
    is_healthy: bool
    status_code: int | None
    latency_ms: float | None
    response_size_bytes: int | None
    content_type: str | None
    error_message: str | None
    schema_status: str
    schema_hash: str | None
    drift_severity: str | None
    change_count: int
    baseline_id: uuid.UUID | None
    incident_id: uuid.UUID | None
    snapshot_id: str | None


class SchemaChangeOut(BaseModel):
    path: str
    kind: str
    rule: str
    severity: str
    old: str | None
    new: str | None
    description: str


class BaselineOut(ORMModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    version: int
    schema_hash: str
    is_current: bool
    source_check_id: uuid.UUID | None
    approved_by_id: uuid.UUID | None
    approved_at: datetime
    replaced_at: datetime | None


class BaselineDetail(BaselineOut):
    json_schema: dict[str, Any] | None  # None when the document store is unavailable


class SchemaView(BaseModel):
    """Everything the schema-comparison screen needs in one response."""

    baseline: BaselineDetail | None
    latest_schema_hash: str | None
    latest_schema: dict[str, Any] | None
    latest_check_id: uuid.UUID | None
    latest_checked_at: datetime | None
    latest_is_json: bool  # only JSON responses can be accepted as a baseline
    comparison_available: bool
    changes: list[SchemaChangeOut]
    max_severity: str | None


class AcceptBaselineRequest(StrictModel):
    check_id: uuid.UUID


class LatencyPoint(BaseModel):
    checked_at: datetime
    latency_ms: float | None
    is_healthy: bool


class MetricsOut(BaseModel):
    window_hours: int
    total_checks: int
    healthy_checks: int
    availability_percent: float | None
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    series: list[LatencyPoint]
