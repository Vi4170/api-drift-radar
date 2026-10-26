import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import AppSettings, CurrentUser, DbSession, Docs, Monitor, Policy
from app.core.errors import RateLimitedError
from app.models import Endpoint
from app.models.enums import CheckOutcome, CheckTrigger, HealthStatus, SchemaStatus
from app.repositories.endpoints import EndpointRepository
from app.repositories.monitoring import BaselineRepository, CheckRepository
from app.schemas.common import Page
from app.schemas.endpoint import EndpointCreate, EndpointOut, EndpointUpdate
from app.schemas.monitoring import (
    AcceptBaselineRequest,
    BaselineOut,
    CheckResultOut,
    MetricsOut,
    SchemaView,
)
from app.security.rate_limit import RateLimiter
from app.services.baseline_service import BaselineService
from app.services.endpoint_service import EndpointService
from app.services.reporting_service import ReportingService

router = APIRouter(prefix="/endpoints", tags=["endpoints"])

PageNumber = Annotated[int, Query(ge=1, le=10_000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def _out(db: DbSession, endpoints: list[Endpoint]) -> list[EndpointOut]:
    repo = EndpointRepository(db)
    ids = [e.id for e in endpoints]
    counts, versions = repo.open_incident_counts(ids), repo.baseline_versions(ids)
    return [
        EndpointOut.model_validate(e).model_copy(
            update={"open_incident_count": counts.get(e.id, 0), "baseline_version": versions.get(e.id)}
        )
        for e in endpoints
    ]


@router.get("", response_model=Page[EndpointOut])
def list_endpoints(
    user: CurrentUser,
    db: DbSession,
    search: Annotated[str | None, Query(max_length=200)] = None,
    health: HealthStatus | None = None,
    schema_status: SchemaStatus | None = None,
    is_active: bool | None = None,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[EndpointOut]:
    items, total = EndpointRepository(db).list_owned(
        user.id,
        search=search,
        health=health,
        schema_status=schema_status,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return Page(items=_out(db, items), total=total, page=page, page_size=page_size)


@router.post("", response_model=EndpointOut, status_code=status.HTTP_201_CREATED)
def create_endpoint(
    payload: EndpointCreate,
    user: CurrentUser,
    db: DbSession,
    docs: Docs,
    policy: Policy,
    settings: AppSettings,
) -> EndpointOut:
    endpoint = EndpointService(db, docs, policy, settings).create(user.id, payload)
    return _out(db, [endpoint])[0]


@router.get("/{endpoint_id}", response_model=EndpointOut)
def get_endpoint(endpoint_id: uuid.UUID, user: CurrentUser, db: DbSession) -> EndpointOut:
    return _out(db, [EndpointRepository(db).get_owned(user.id, endpoint_id)])[0]


@router.patch("/{endpoint_id}", response_model=EndpointOut)
def update_endpoint(
    endpoint_id: uuid.UUID,
    payload: EndpointUpdate,
    user: CurrentUser,
    db: DbSession,
    docs: Docs,
    policy: Policy,
    settings: AppSettings,
) -> EndpointOut:
    """Partial update. Set `is_active` to pause or resume scheduled monitoring."""
    endpoint = EndpointService(db, docs, policy, settings).update(user.id, endpoint_id, payload)
    return _out(db, [endpoint])[0]


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_endpoint(
    endpoint_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    docs: Docs,
    policy: Policy,
    settings: AppSettings,
) -> Response:
    EndpointService(db, docs, policy, settings).delete(user.id, endpoint_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{endpoint_id}/checks", response_model=CheckResultOut, status_code=status.HTTP_201_CREATED)
def run_manual_check(
    endpoint_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    monitor: Monitor,
    settings: AppSettings,
) -> CheckResultOut:
    """Run a health + schema check now (works without the worker running)."""
    endpoint = EndpointRepository(db).get_owned(user.id, endpoint_id)
    cooldown = timedelta(seconds=settings.manual_check_cooldown_seconds)
    if endpoint.last_checked_at and datetime.now(UTC) - endpoint.last_checked_at < cooldown:
        raise RateLimitedError(f"Please wait {settings.manual_check_cooldown_seconds}s between checks")
    limiter: RateLimiter = request.app.state.check_limiter
    limiter.hit(str(user.id))
    db.close()  # release the connection while the outbound request runs
    check = monitor.run_check(endpoint_id, CheckTrigger.MANUAL)
    return CheckResultOut.model_validate(check)


@router.get("/{endpoint_id}/checks", response_model=Page[CheckResultOut])
def list_checks(
    endpoint_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    outcome: CheckOutcome | None = None,
    healthy: bool | None = None,
    since: datetime | None = None,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[CheckResultOut]:
    endpoint = EndpointRepository(db).get_owned(user.id, endpoint_id)
    rows, total = CheckRepository(db).list_for_endpoint(
        endpoint.id, outcome=outcome, healthy=healthy, since=since, page=page, page_size=page_size
    )
    return Page(
        items=[CheckResultOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/{endpoint_id}/schema", response_model=SchemaView)
def get_schema_view(endpoint_id: uuid.UUID, user: CurrentUser, db: DbSession, docs: Docs) -> SchemaView:
    """Approved baseline, latest observed schema and the classified differences between them."""
    return ReportingService(db, docs).schema_view(user.id, endpoint_id)


@router.get("/{endpoint_id}/baselines", response_model=list[BaselineOut])
def list_baselines(endpoint_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[BaselineOut]:
    """Baseline version history, newest first."""
    endpoint = EndpointRepository(db).get_owned(user.id, endpoint_id)
    return [BaselineOut.model_validate(b) for b in BaselineRepository(db).history(endpoint.id)]


@router.post("/{endpoint_id}/baseline", response_model=BaselineOut, status_code=status.HTTP_201_CREATED)
def accept_baseline(
    endpoint_id: uuid.UUID, payload: AcceptBaselineRequest, user: CurrentUser, db: DbSession, docs: Docs
) -> BaselineOut:
    """Explicitly approve the schema observed by `check_id` as the new baseline."""
    return BaselineOut.model_validate(
        BaselineService(db, docs).accept(user.id, endpoint_id, payload.check_id)
    )


@router.get("/{endpoint_id}/metrics", response_model=MetricsOut)
def get_metrics(
    endpoint_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    docs: Docs,
    window_hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> MetricsOut:
    """Latency and availability over the last `window_hours`."""
    return ReportingService(db, docs).metrics(user.id, endpoint_id, window_hours)
