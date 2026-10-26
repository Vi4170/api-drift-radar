import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import Endpoint, Incident, IncidentEvent
from app.models.enums import IncidentStatus


class IncidentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_owned(self, owner_id: uuid.UUID, incident_id: uuid.UUID) -> tuple[Incident, str]:
        row = self.db.execute(
            select(Incident, Endpoint.name)
            .join(Endpoint, Endpoint.id == Incident.endpoint_id)
            .where(Incident.id == incident_id, Endpoint.owner_id == owner_id)
        ).first()
        if row is None:
            raise NotFoundError("Incident not found")
        return row[0], row[1]

    def get_open(self, endpoint_id: uuid.UUID, type_: str) -> Incident | None:
        return self.db.scalar(
            select(Incident).where(
                Incident.endpoint_id == endpoint_id,
                Incident.type == type_,
                Incident.status == IncidentStatus.OPEN,
            )
        )

    def list_owned(
        self,
        owner_id: uuid.UUID,
        *,
        status: str | None = None,
        severity: str | None = None,
        type_: str | None = None,
        endpoint_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[tuple[Incident, str]], int]:
        query = (
            select(Incident, Endpoint.name)
            .join(Endpoint, Endpoint.id == Incident.endpoint_id)
            .where(Endpoint.owner_id == owner_id)
        )
        if status:
            query = query.where(Incident.status == status)
        if severity:
            query = query.where(Incident.severity == severity)
        if type_:
            query = query.where(Incident.type == type_)
        if endpoint_id:
            query = query.where(Incident.endpoint_id == endpoint_id)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.execute(
            query.order_by(Incident.last_seen_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return [(incident, name) for incident, name in rows], total

    def open_counts_by_severity(self, owner_id: uuid.UUID) -> dict[str, int]:
        rows = self.db.execute(
            select(Incident.severity, func.count())
            .join(Endpoint, Endpoint.id == Incident.endpoint_id)
            .where(Endpoint.owner_id == owner_id, Incident.status == IncidentStatus.OPEN)
            .group_by(Incident.severity)
        ).all()
        return {severity: count for severity, count in rows}

    def events(self, incident_id: uuid.UUID) -> list[IncidentEvent]:
        return list(
            self.db.scalars(
                select(IncidentEvent)
                .where(IncidentEvent.incident_id == incident_id)
                .order_by(IncidentEvent.created_at, IncidentEvent.id)
            )
        )
