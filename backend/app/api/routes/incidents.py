import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, Docs
from app.models.enums import IncidentStatus, IncidentType, Severity
from app.repositories.incidents import IncidentRepository
from app.schemas.common import Page
from app.schemas.dashboard import DashboardSummary
from app.schemas.incident import IncidentDetail, IncidentOut, ResolveIncidentRequest
from app.services.endpoint_service import record_audit
from app.services.incident_service import IncidentService
from app.services.reporting_service import ReportingService, incident_out

router = APIRouter(tags=["incidents"])


@router.get("/incidents", response_model=Page[IncidentOut])
def list_incidents(
    user: CurrentUser,
    db: DbSession,
    status: IncidentStatus | None = None,
    severity: Severity | None = None,
    type: IncidentType | None = None,  # noqa: A002 - public query parameter name
    endpoint_id: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[IncidentOut]:
    rows, total = IncidentRepository(db).list_owned(
        user.id,
        status=status,
        severity=severity,
        type_=type,
        endpoint_id=endpoint_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[incident_out(i, name) for i, name in rows], total=total, page=page, page_size=page_size
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: uuid.UUID, user: CurrentUser, db: DbSession, docs: Docs) -> IncidentDetail:
    """Incident with its full event history and (for drift) the classified schema changes."""
    return ReportingService(db, docs).incident_detail(user.id, incident_id)


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentDetail)
def resolve_incident(
    incident_id: uuid.UUID, payload: ResolveIncidentRequest, user: CurrentUser, db: DbSession, docs: Docs
) -> IncidentDetail:
    """Manually resolve an open incident. If the drift persists, the next check opens a new one;
    to make a changed schema the new normal, accept it as the baseline instead."""
    incident, _ = IncidentRepository(db).get_owned(user.id, incident_id)
    IncidentService(db).resolve_manually(incident, user.id, payload.note, datetime.now(UTC))
    record_audit(db, user.id, "incident.resolved", incident.endpoint_id, incident_id=str(incident.id))
    db.commit()
    return ReportingService(db, docs).incident_detail(user.id, incident_id)


@router.get("/dashboard/summary", response_model=DashboardSummary, tags=["dashboard"])
def dashboard_summary(user: CurrentUser, db: DbSession, docs: Docs) -> DashboardSummary:
    return ReportingService(db, docs).dashboard(user.id)
