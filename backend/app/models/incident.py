import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.sql import Base, UTCDateTime, utcnow


class Incident(Base):
    """An open or resolved problem. At most one OPEN incident per (endpoint, type) is allowed,
    enforced by a partial unique index, so repeated polls update rather than duplicate."""

    __tablename__ = "incidents"
    __table_args__ = (
        Index(
            "uq_incidents_one_open",
            "endpoint_id",
            "type",
            unique=True,
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
        Index("ix_incidents_endpoint_status", "endpoint_id", "status"),
        Index("ix_incidents_last_seen", "last_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="open")
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(1000))
    # For drift: the observed schema hash; identical drift => identical fingerprint.
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    baseline_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("baselines.id", ondelete="SET NULL"))
    latest_diff_id: Mapped[str | None] = mapped_column(String(200))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolution: Mapped[str | None] = mapped_column(String(32))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class IncidentEvent(Base):
    """Lifecycle history of an incident (opened, changed, resolved...). Identical repeat
    observations only bump Incident.occurrence_count, so history stays bounded."""

    __tablename__ = "incident_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    event_type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(500))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditEvent(Base):
    """User-initiated actions. endpoint_id is deliberately not a foreign key so the audit
    trail survives endpoint deletion."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
