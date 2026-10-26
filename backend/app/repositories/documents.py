"""MongoDB document store for schemas, response snapshots and diff documents.

Document ids are deterministic (see app/database/mongo.py), so every write is an idempotent
upsert: a retried or duplicated monitoring run can never create conflicting documents.

Schemas and response bodies are stored as JSON strings: their keys come from arbitrary third-party
APIs and may contain "." or "$", which MongoDB field names handle poorly.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.monitoring.schema_inference import SchemaNode, canonical_json, schema_hash


class DocumentStoreError(Exception):
    """The document database is unavailable or returned inconsistent data."""


def schema_doc_id(endpoint_id: uuid.UUID, hash_: str) -> str:
    return f"{endpoint_id}:{hash_}"


def diff_doc_id(endpoint_id: uuid.UUID, baseline_hash: str, observed_hash: str) -> str:
    return f"{endpoint_id}:{baseline_hash}:{observed_hash}"


class DocumentStore:
    def __init__(self, db: Database):
        self.db = db

    def _run(self, action: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except PyMongoError as exc:
            raise DocumentStoreError(f"Document store unavailable while trying to {action}") from exc

    def save_schema(self, endpoint_id: uuid.UUID, schema: SchemaNode) -> str:
        hash_ = schema_hash(schema)
        self._run(
            "save schema",
            self.db.schemas.update_one,
            {"_id": schema_doc_id(endpoint_id, hash_)},
            {
                "$setOnInsert": {
                    "endpoint_id": str(endpoint_id),
                    "schema_hash": hash_,
                    "schema_json": canonical_json(schema),
                    "created_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
        return hash_

    def get_schema(self, endpoint_id: uuid.UUID, hash_: str) -> SchemaNode | None:
        doc = self._run("load schema", self.db.schemas.find_one, {"_id": schema_doc_id(endpoint_id, hash_)})
        if doc is None:
            return None
        schema = json.loads(doc["schema_json"])
        if schema_hash(schema) != hash_:
            raise DocumentStoreError("Stored schema failed its integrity check")
        return schema

    def save_snapshot(
        self, check_id: uuid.UUID, endpoint_id: uuid.UUID, body: Any, status_code: int, schema_hash_: str
    ) -> str:
        doc = {
            "endpoint_id": str(endpoint_id),
            "check_id": str(check_id),
            "status_code": status_code,
            "schema_hash": schema_hash_,
            "body_json": json.dumps(body),
            "captured_at": datetime.now(UTC),
        }
        self._run("save snapshot", self.db.snapshots.replace_one, {"_id": str(check_id)}, doc, upsert=True)
        return str(check_id)

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return self._run("load snapshot", self.db.snapshots.find_one, {"_id": snapshot_id})

    def delete_snapshot(self, snapshot_id: str) -> None:
        self._run("delete snapshot", self.db.snapshots.delete_one, {"_id": snapshot_id})

    def save_diff(
        self,
        endpoint_id: uuid.UUID,
        baseline_hash: str,
        observed_hash: str,
        changes: list[dict[str, Any]],
        counts: dict[str, int],
    ) -> str:
        doc_id = diff_doc_id(endpoint_id, baseline_hash, observed_hash)
        self._run(
            "save diff",
            self.db.diffs.update_one,
            {"_id": doc_id},
            {
                "$setOnInsert": {
                    "endpoint_id": str(endpoint_id),
                    "baseline_hash": baseline_hash,
                    "observed_hash": observed_hash,
                    "changes": changes,
                    "counts": counts,
                    "created_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
        return doc_id

    def get_diff(self, diff_id: str) -> dict[str, Any] | None:
        return self._run("load diff", self.db.diffs.find_one, {"_id": diff_id})

    def delete_endpoint_documents(self, endpoint_id: uuid.UUID) -> None:
        for collection in (self.db.snapshots, self.db.schemas, self.db.diffs):
            self._run("delete documents", collection.delete_many, {"endpoint_id": str(endpoint_id)})

    def ensure_indexes(self, snapshot_retention_days: int) -> None:
        self.db.snapshots.create_index([("endpoint_id", ASCENDING), ("captured_at", DESCENDING)])
        self.db.snapshots.create_index(
            "captured_at", name="snapshot_ttl", expireAfterSeconds=snapshot_retention_days * 86400
        )
        self.db.schemas.create_index("endpoint_id")
        self.db.diffs.create_index("endpoint_id")

    def ping(self) -> bool:
        try:
            self.db.command("ping")
            return True
        except PyMongoError:
            return False
