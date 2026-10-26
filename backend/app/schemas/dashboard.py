from datetime import datetime

from pydantic import BaseModel

from app.schemas.incident import IncidentOut
from app.schemas.monitoring import CheckResultOut


class RecentCheckOut(CheckResultOut):
    endpoint_name: str


class LatencyBucket(BaseModel):
    bucket_start: datetime
    checks: int
    healthy_checks: int
    avg_latency_ms: float | None


class DashboardSummary(BaseModel):
    total_endpoints: int
    active_endpoints: int
    healthy_endpoints: int
    unhealthy_endpoints: int
    unknown_endpoints: int
    endpoints_with_open_drift: int
    open_incidents_by_severity: dict[str, int]
    checks_last_24h: int
    availability_24h_percent: float | None
    avg_latency_24h_ms: float | None
    recent_incidents: list[IncidentOut]
    recent_checks: list[RecentCheckOut]
    latency_series: list[LatencyBucket]
