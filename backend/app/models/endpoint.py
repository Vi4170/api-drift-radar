import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.sql import Base, UTCDateTime, utcnow
from app.models.enums import HealthStatus, SchemaStatus


class Endpoint(Base):
    """A monitored HTTP endpoint plus a denormalised summary of its latest state."""

    __tablename__ = "endpoints"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_endpoints_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2048))
    method: Mapped[str] = mapped_column(String(10), default="GET")
    expected_status: Mapped[int] = mapped_column(Integer, default=200)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=10.0)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    # Latest-state summary (written by MonitoringService, never by API clients)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_outcome: Mapped[str | None] = mapped_column(String(32))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_latency_ms: Mapped[float | None] = mapped_column(Float)
    health_status: Mapped[str] = mapped_column(String(16), default=HealthStatus.UNKNOWN)
    schema_status: Mapped[str] = mapped_column(String(32), default=SchemaStatus.UNKNOWN)
    schema_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    latest_schema_hash: Mapped[str | None] = mapped_column(String(64))
