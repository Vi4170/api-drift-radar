import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, ValidationFailedError
from app.models import AuditEvent, Endpoint
from app.models.enums import HealthStatus, SchemaStatus
from app.repositories.documents import DocumentStore, DocumentStoreError
from app.repositories.endpoints import EndpointRepository
from app.schemas.endpoint import EndpointCreate, EndpointUpdate
from app.security.ssrf import DestinationPolicy

logger = logging.getLogger(__name__)


def record_audit(
    db: Session, user_id: uuid.UUID | None, action: str, endpoint_id: uuid.UUID | None = None, **details: Any
) -> None:
    db.add(AuditEvent(user_id=user_id, endpoint_id=endpoint_id, action=action, details=details))


class EndpointService:
    def __init__(self, db: Session, docs: DocumentStore, policy: DestinationPolicy, settings: Settings):
        self.db = db
        self.docs = docs
        self.policy = policy
        self.settings = settings
        self.repo = EndpointRepository(db)

    def _validate(
        self, owner_id: uuid.UUID, data: dict[str, Any], exclude_id: uuid.UUID | None = None
    ) -> None:
        """Service-layer checks that depend on configuration, DNS or other rows."""
        if "url" in data:
            self.policy.check_url(data["url"])  # raises UnsafeURLError (422)
        interval = data.get("interval_seconds")
        if interval is not None and interval < self.settings.monitor_min_interval_seconds:
            raise ValidationFailedError(
                f"interval_seconds must be at least {self.settings.monitor_min_interval_seconds}"
            )
        timeout = data.get("timeout_seconds")
        if timeout is not None and timeout > self.settings.monitor_max_timeout_seconds:
            raise ValidationFailedError(
                f"timeout_seconds must be at most {self.settings.monitor_max_timeout_seconds}"
            )
        if "name" in data and self.repo.name_taken(owner_id, data["name"], exclude_id):
            raise ConflictError("An endpoint with this name already exists")

    def create(self, owner_id: uuid.UUID, payload: EndpointCreate) -> Endpoint:
        data = payload.model_dump()
        self._validate(owner_id, data)
        endpoint = Endpoint(owner_id=owner_id, **data)
        self.db.add(endpoint)
        self.db.flush()
        record_audit(self.db, owner_id, "endpoint.created", endpoint.id, name=endpoint.name)
        self.db.commit()
        return endpoint

    def update(self, owner_id: uuid.UUID, endpoint_id: uuid.UUID, payload: EndpointUpdate) -> Endpoint:
        endpoint = self.repo.get_owned(owner_id, endpoint_id, lock=True)
        data = payload.model_dump(exclude_unset=True)
        if any(data.get(key) is None for key in data if key != "headers"):
            raise ValidationFailedError("Fields cannot be set to null")
        self._validate(owner_id, data, exclude_id=endpoint.id)
        url_changed = "url" in data and data["url"] != endpoint.url
        for key, value in data.items():
            setattr(endpoint, key, value if value is not None else {})
        if url_changed:
            # New target: previous health no longer applies. The baseline is kept and the
            # next check is compared against it - accepting a new one stays an explicit action.
            endpoint.health_status = HealthStatus.UNKNOWN
            endpoint.schema_status = SchemaStatus.UNKNOWN
        record_audit(self.db, owner_id, "endpoint.updated", endpoint.id, fields=sorted(data))
        self.db.commit()
        return endpoint

    def delete(self, owner_id: uuid.UUID, endpoint_id: uuid.UUID) -> None:
        endpoint = self.repo.get_owned(owner_id, endpoint_id, lock=True)
        name = endpoint.name
        self.db.delete(endpoint)  # FK cascades remove checks, baselines and incidents
        record_audit(self.db, owner_id, "endpoint.deleted", endpoint_id, name=name)
        self.db.commit()
        # Documents are removed after the SQL commit. If this fails the documents are orphaned
        # (unreachable, keyed by a deleted id) and snapshots still expire through their TTL.
        try:
            self.docs.delete_endpoint_documents(endpoint_id)
        except DocumentStoreError:
            logger.warning(
                "Could not delete documents for deleted endpoint %s; they are orphaned", endpoint_id
            )
