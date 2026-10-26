import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Baseline, CheckResult, Endpoint


class CheckRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_endpoint(self, endpoint_id: uuid.UUID, check_id: uuid.UUID) -> CheckResult | None:
        return self.db.scalar(
            select(CheckResult).where(CheckResult.id == check_id, CheckResult.endpoint_id == endpoint_id)
        )

    def list_for_endpoint(
        self,
        endpoint_id: uuid.UUID,
        *,
        outcome: str | None,
        healthy: bool | None,
        since: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[CheckResult], int]:
        query = select(CheckResult).where(CheckResult.endpoint_id == endpoint_id)
        if outcome:
            query = query.where(CheckResult.outcome == outcome)
        if healthy is not None:
            query = query.where(CheckResult.is_healthy == healthy)
        if since is not None:
            query = query.where(CheckResult.checked_at >= since)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.scalars(
            query.order_by(CheckResult.checked_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), total

    def latest_schema_check(self, endpoint_id: uuid.UUID) -> CheckResult | None:
        """Most recent check that produced a schema (a JSON or non-JSON successful response)."""
        return self.db.scalar(
            select(CheckResult)
            .where(CheckResult.endpoint_id == endpoint_id, CheckResult.schema_hash.is_not(None))
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )

    def window(self, endpoint_ids: list[uuid.UUID] | None, since: datetime, limit: int) -> list[CheckResult]:
        """Most recent checks since `since`, newest first, capped at `limit` rows."""
        query = select(CheckResult).where(CheckResult.checked_at >= since)
        if endpoint_ids is not None:
            query = query.where(CheckResult.endpoint_id.in_(endpoint_ids))
        return list(self.db.scalars(query.order_by(CheckResult.checked_at.desc()).limit(limit)))

    def stats(self, endpoint_ids: list[uuid.UUID], since: datetime) -> tuple[int, int, float | None]:
        """(total, healthy, avg latency) computed in the database, not in memory."""
        if not endpoint_ids:
            return 0, 0, None
        row = self.db.execute(
            select(
                func.count(),
                func.count().filter(CheckResult.is_healthy.is_(True)),
                func.avg(CheckResult.latency_ms),
            ).where(CheckResult.endpoint_id.in_(endpoint_ids), CheckResult.checked_at >= since)
        ).one()
        return int(row[0]), int(row[1]), float(row[2]) if row[2] is not None else None

    def recent_for_owner(self, owner_id: uuid.UUID, limit: int) -> list[tuple[CheckResult, str]]:
        rows = self.db.execute(
            select(CheckResult, Endpoint.name)
            .join(Endpoint, Endpoint.id == CheckResult.endpoint_id)
            .where(Endpoint.owner_id == owner_id)
            .order_by(CheckResult.checked_at.desc())
            .limit(limit)
        ).all()
        return [(check, name) for check, name in rows]


class BaselineRepository:
    def __init__(self, db: Session):
        self.db = db

    def current(self, endpoint_id: uuid.UUID) -> Baseline | None:
        return self.db.scalar(
            select(Baseline).where(Baseline.endpoint_id == endpoint_id, Baseline.is_current.is_(True))
        )

    def history(self, endpoint_id: uuid.UUID) -> list[Baseline]:
        return list(
            self.db.scalars(
                select(Baseline).where(Baseline.endpoint_id == endpoint_id).order_by(Baseline.version.desc())
            )
        )

    def next_version(self, endpoint_id: uuid.UUID) -> int:
        latest = self.db.scalar(select(func.max(Baseline.version)).where(Baseline.endpoint_id == endpoint_id))
        return (latest or 0) + 1
