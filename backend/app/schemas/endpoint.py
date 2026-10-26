import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import ORMModel, StrictModel

_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
_FORBIDDEN_HEADERS = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "upgrade",
    "te",
    "trailer",
    "keep-alive",
    "forwarded",
    "x-real-ip",
    "expect",
}
_FORBIDDEN_PREFIXES = ("proxy-", "x-forwarded-", "sec-")

MAX_HEADERS = 20


def validate_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    if headers is None:
        return None
    if len(headers) > MAX_HEADERS:
        raise ValueError(f"At most {MAX_HEADERS} headers are allowed")
    for name, value in headers.items():
        lowered = name.lower()
        if not _HEADER_NAME.match(name):
            raise ValueError(f"Invalid header name: {name!r}")
        if lowered in _FORBIDDEN_HEADERS or lowered.startswith(_FORBIDDEN_PREFIXES):
            raise ValueError(f"Header {name!r} is managed by the monitor and cannot be set")
        if len(value) > 1024 or any(c in value for c in "\r\n\0"):
            raise ValueError(f"Invalid value for header {name!r}")
    return headers


class EndpointBase(StrictModel):
    @field_validator("headers", check_fields=False)
    @classmethod
    def _headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return validate_headers(value)

    @field_validator("url", check_fields=False)
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is not None and not value.lower().startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return value


class EndpointCreate(EndpointBase):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=2048)
    method: Literal["GET"] = "GET"
    expected_status: int = Field(default=200, ge=100, le=599)
    interval_seconds: int = Field(default=300, ge=30, le=86400)
    timeout_seconds: float = Field(default=10.0, ge=1, le=30)
    headers: dict[str, str] = Field(default_factory=dict)
    is_active: bool = True


class EndpointUpdate(EndpointBase):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=8, max_length=2048)
    method: Literal["GET"] | None = None
    expected_status: int | None = Field(default=None, ge=100, le=599)
    interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    timeout_seconds: float | None = Field(default=None, ge=1, le=30)
    headers: dict[str, str] | None = None
    is_active: bool | None = None


class EndpointOut(ORMModel):
    id: uuid.UUID
    name: str
    url: str
    method: str
    expected_status: int
    interval_seconds: int
    timeout_seconds: float
    headers: dict[str, str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
    last_outcome: str | None
    last_status_code: int | None
    last_latency_ms: float | None
    health_status: str
    schema_status: str
    schema_checked_at: datetime | None
    latest_schema_hash: str | None
    open_incident_count: int = 0
    baseline_version: int | None = None
