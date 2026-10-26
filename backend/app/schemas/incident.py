import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ORMModel, StrictModel
from app.schemas.monitoring import SchemaChangeOut


class IncidentOut(ORMModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    endpoint_name: str = ""
    type: str
    status: str
    severity: str
    title: str
    summary: str
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    resolution: str | None
    baseline_id: uuid.UUID | None


class IncidentEventOut(ORMModel):
    id: uuid.UUID
    created_at: datetime
    event_type: str
    message: str
    actor_id: uuid.UUID | None
    details: dict[str, Any]


class IncidentDetail(IncidentOut):
    events: list[IncidentEventOut]
    changes: list[SchemaChangeOut]
    changes_available: bool


class ResolveIncidentRequest(StrictModel):
    note: str = Field(default="", max_length=500)
