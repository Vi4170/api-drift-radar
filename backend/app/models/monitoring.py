import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.sql import Base, UTCDateTime, utcnow


class Baseline(Base):
    """An approved schema version for an endpoint. The schema body lives in MongoDB
    (`schemas` collection, keyed by endpoint + schema_hash); the hash doubles as an
    integrity check when the document is loaded. Exactly one baseline per endpoint is current.
    """

    __tablename__ = "baselines"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "version", name="uq_baselines_endpoint_version"),
        Index(
            "uq_baselines_one_current",
            "endpoint_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    schema_hash: Mapped[str] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    source_check_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("check_results.id", ondelete="SET NULL")
    )
    # NULL approver = initial baseline created automatically from the first JSON response.
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    replaced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class CheckResult(Base):
    """Summary of a single monitoring run. Raw body/schema/diff documents are in MongoDB."""

    __tablename__ = "check_results"
    __table_args__ = (Index("ix_check_results_endpoint_checked", "endpoint_id", "checked_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    trigger: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(32))
    is_healthy: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    response_size_bytes: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(String(500))
    schema_status: Mapped[str] = mapped_column(String(32))
    schema_hash: Mapped[str | None] = mapped_column(String(64))
    drift_severity: Mapped[str | None] = mapped_column(String(16))
    change_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("baselines.id", ondelete="SET NULL", use_alter=True)
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL", use_alter=True)
    )
    # References into MongoDB (None when the document could not be written)
    snapshot_id: Mapped[str | None] = mapped_column(String(64))
    diff_id: Mapped[str | None] = mapped_column(String(200))
