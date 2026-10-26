"""Approved-baseline management.

The baseline only changes in two ways:
  1. automatically, exactly once, from the first successful JSON response (version 1);
  2. explicitly, when an authorised owner accepts the schema observed by a specific check.
Failed checks, non-JSON responses and drifted responses never touch it.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models import Baseline, Endpoint
from app.models.enums import CheckOutcome, SchemaStatus
from app.repositories.documents import DocumentStore
from app.repositories.endpoints import EndpointRepository
from app.repositories.monitoring import BaselineRepository, CheckRepository
from app.services.endpoint_service import record_audit
from app.services.incident_service import IncidentService


class BaselineService:
    def __init__(self, db: Session, docs: DocumentStore):
        self.db = db
        self.docs = docs
        self.repo = BaselineRepository(db)

    def create_initial(
        self, endpoint: Endpoint, schema_hash: str, check_id: uuid.UUID, now: datetime
    ) -> Baseline:
        if self.repo.current(endpoint.id) is not None:
            raise ConflictError("Endpoint already has a baseline")
        baseline = Baseline(
            endpoint_id=endpoint.id,
            version=self.repo.next_version(endpoint.id),
            schema_hash=schema_hash,
            is_current=True,
            source_check_id=check_id,
            approved_by_id=None,
            approved_at=now,
        )
        self.db.add(baseline)
        self.db.flush()
        return baseline

    def accept(self, owner_id: uuid.UUID, endpoint_id: uuid.UUID, check_id: uuid.UUID) -> Baseline:
        """Promote the schema observed by `check_id` to the approved baseline."""
        endpoint = EndpointRepository(self.db).get_owned(owner_id, endpoint_id, lock=True)
        check = CheckRepository(self.db).get_for_endpoint(endpoint.id, check_id)
        if check is None:
            raise NotFoundError("Check not found for this endpoint")
        if check.outcome != CheckOutcome.SUCCESS_JSON or not check.schema_hash:
            raise ValidationFailedError("Only a successful JSON check can become a baseline")
        # The schema document must exist (and pass its integrity check) before we point at it.
        if self.docs.get_schema(endpoint.id, check.schema_hash) is None:
            raise ConflictError("The schema for this check is no longer available; run a new check")

        now = datetime.now(UTC)
        previous = self.repo.current(endpoint.id)
        if previous is not None:
            if previous.schema_hash == check.schema_hash:
                raise ConflictError("This schema is already the approved baseline")
            previous.is_current = False
            previous.replaced_at = now
            self.db.flush()  # free the one-current-baseline unique index before inserting
        baseline = Baseline(
            endpoint_id=endpoint.id,
            version=self.repo.next_version(endpoint.id),
            schema_hash=check.schema_hash,
            is_current=True,
            source_check_id=check.id,
            approved_by_id=owner_id,
            approved_at=now,
        )
        self.db.add(baseline)
        self.db.flush()

        message = f"New baseline v{baseline.version} accepted"
        IncidentService(self.db).clear_drift(endpoint, "baseline_accepted", now, owner_id, message)
        endpoint.schema_status = (
            SchemaStatus.COMPATIBLE
            if endpoint.latest_schema_hash == check.schema_hash
            else SchemaStatus.UNKNOWN
        )
        record_audit(
            self.db,
            owner_id,
            "baseline.accepted",
            endpoint.id,
            check_id=str(check.id),
            version=baseline.version,
            previous_version=previous.version if previous else None,
        )
        self.db.commit()
        return baseline
