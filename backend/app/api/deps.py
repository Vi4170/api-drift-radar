"""FastAPI dependencies. Long-lived collaborators are built once and can be replaced in tests
through `app.dependency_overrides`."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError
from app.database.mongo import get_mongo_db
from app.database.sql import get_db, get_session_factory
from app.models import User
from app.monitoring.http_client import SafeHTTPClient
from app.repositories.documents import DocumentStore
from app.security.auth import decode_access_token
from app.security.ssrf import DestinationPolicy
from app.services.monitoring_service import MonitoringService

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_document_store() -> DocumentStore:
    return DocumentStore(get_mongo_db())


def get_destination_policy() -> DestinationPolicy:
    return DestinationPolicy(allowed_hosts=get_settings().monitor_allowed_hosts)


@lru_cache
def get_monitoring_service() -> MonitoringService:
    settings = get_settings()
    http = SafeHTTPClient(
        get_destination_policy(),
        max_response_bytes=settings.monitor_max_response_bytes,
        max_retries=settings.monitor_max_retries,
        user_agent=settings.monitor_user_agent,
        max_connections=settings.monitor_max_concurrency * 2,
    )
    return MonitoringService(get_session_factory(), http, get_document_store())


def get_current_user(
    db: DbSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Not authenticated")
    user_id = decode_access_token(credentials.credentials, settings.jwt_secret, settings.jwt_algorithm)
    user = db.get(User, user_id)
    if user is None:
        raise AuthenticationError("Invalid token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
Docs = Annotated[DocumentStore, Depends(get_document_store)]
Policy = Annotated[DestinationPolicy, Depends(get_destination_policy)]
Monitor = Annotated[MonitoringService, Depends(get_monitoring_service)]
