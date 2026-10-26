"""Owner-scoped endpoint queries. Every lookup takes owner_id, so cross-user access is
impossible by construction (another user's endpoint is simply 'not found')."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import Baseline, Endpoint, Incident
from app.models.enums import IncidentStatus, IncidentType


class EndpointRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_owned(self, owner_id: uuid.UUID, endpoint_id: uuid.UUID, *, lock: bool = False) -> Endpoint:
        query = select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.owner_id == owner_id)
        if lock:
            query = query.with_for_update()
        endpoint = self.db.scalar(query)
        if endpoint is None:
            raise NotFoundError("Endpoint not found")
        return endpoint

    def get_for_update(self, endpoint_id: uuid.UUID) -> Endpoint | None:
        """Row lock used by the monitoring pipeline to serialise result recording."""
        return self.db.scalar(select(Endpoint).where(Endpoint.id == endpoint_id).with_for_update())

    def name_taken(self, owner_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None) -> bool:
        query = select(Endpoint.id).where(Endpoint.owner_id == owner_id, Endpoint.name == name)
        if exclude_id is not None:
            query = query.where(Endpoint.id != exclude_id)
        return self.db.scalar(query) is not None

    def list_owned(
        self,
        owner_id: uuid.UUID,
        *,
        search: str | None,
        health: str | None,
        schema_status: str | None,
        is_active: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Endpoint], int]:
        query = select(Endpoint).where(Endpoint.owner_id == owner_id)
        if search:
            pattern = f"%{search.lower()}%"
            query = query.where(
                or_(func.lower(Endpoint.name).like(pattern), func.lower(Endpoint.url).like(pattern))
            )
        if health:
            query = query.where(Endpoint.health_status == health)
        if schema_status:
            query = query.where(Endpoint.schema_status == schema_status)
        if is_active is not None:
            query = query.where(Endpoint.is_active == is_active)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.scalars(
            query.order_by(Endpoint.name).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), total

    def open_incident_counts(self, endpoint_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not endpoint_ids:
            return {}
        rows = self.db.execute(
            select(Incident.endpoint_id, func.count())
            .where(Incident.endpoint_id.in_(endpoint_ids), Incident.status == IncidentStatus.OPEN)
            .group_by(Incident.endpoint_id)
        ).all()
        return {endpoint_id: count for endpoint_id, count in rows}

    def baseline_versions(self, endpoint_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not endpoint_ids:
            return {}
        rows = self.db.execute(
            select(Baseline.endpoint_id, Baseline.version).where(
                Baseline.endpoint_id.in_(endpoint_ids), Baseline.is_current.is_(True)
            )
        ).all()
        return {endpoint_id: version for endpoint_id, version in rows}

    def open_drift_endpoint_count(self, owner_id: uuid.UUID) -> int:
        return (
            self.db.scalar(
                select(func.count(func.distinct(Incident.endpoint_id)))
                .join(Endpoint, Endpoint.id == Incident.endpoint_id)
                .where(
                    Endpoint.owner_id == owner_id,
                    Incident.status == IncidentStatus.OPEN,
                    Incident.type == IncidentType.SCHEMA_DRIFT,
                )
            )
            or 0
        )

    def active_schedule(self) -> list[tuple[uuid.UUID, int]]:
        """(id, interval) of every enabled endpoint, for the scheduler."""
        return [
            (row.id, row.interval_seconds)
            for row in self.db.execute(
                select(Endpoint.id, Endpoint.interval_seconds).where(Endpoint.is_active.is_(True))
            )
        ]
