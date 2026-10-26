import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import RedactingFilter, redact
from app.security.auth import hash_password, verify_password


def test_password_hashing_uses_argon2_and_verifies() -> None:
    hashed = hash_password("hunter2-but-longer")
    assert hashed.startswith("$argon2id$") and "hunter2" not in hashed
    assert verify_password("hunter2-but-longer", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


@pytest.mark.parametrize(
    "secret_text",
    [
        "Authorization: Bearer abc.def.ghi",
        "postgresql://driftradar:supersecret@db:5432/x",
        '{"password": "supersecret"}',
        "x-api-key=supersecret",
    ],
)
def test_redaction(secret_text: str) -> None:
    out = redact(secret_text)
    assert "supersecret" not in out and "abc.def.ghi" not in out and "[REDACTED]" in out


def test_log_filter_redacts_records() -> None:
    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "connecting to %s", ("mongodb://u:pw123@h/db",), None
    )
    RedactingFilter().filter(record)
    assert "pw123" not in record.getMessage()


def test_weak_or_placeholder_secret_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ["short", "change-me-change-me-change-me-change-me-123"]:
        monkeypatch.setenv("JWT_SECRET", value)
        with pytest.raises(ValidationError):
            Settings()


def test_unhandled_errors_do_not_leak_details(client: TestClient, auth: dict, monitor, monkeypatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret internal detail")

    from tests.conftest import create_endpoint

    ep = create_endpoint(client, auth)
    monkeypatch.setattr(monitor, "run_check", explode)
    safe_client = TestClient(client.app, raise_server_exceptions=False)
    response = safe_client.post(f"/api/v1/endpoints/{ep['id']}/checks", headers=auth)
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "An unexpected error occurred", "details": None}
    }


def test_cors_only_allows_configured_origins(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    denied = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers
