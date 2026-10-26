from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from app.core.config import get_settings
from tests.conftest import create_endpoint, register

API = "/api/v1"


# ---- authentication ---------------------------------------------------------------------------


def test_register_login_and_me(client: TestClient) -> None:
    register(client, "Alice@Example.com", "a-long-password")
    login = client.post(
        f"{API}/auth/login", json={"email": "alice@example.com", "password": "a-long-password"}
    )
    assert login.status_code == 200
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"
    assert "password" not in me.text and "hash" not in me.text


def test_duplicate_registration_conflicts(client: TestClient) -> None:
    register(client, "dup@example.com")
    response = client.post(f"{API}/auth/register", json={"email": "dup@example.com", "password": "x" * 12})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_invalid_credentials(client: TestClient) -> None:
    register(client, "bob@example.com", "the-right-password")
    for email, password in [("bob@example.com", "wrong-password"), ("nobody@example.com", "whatever")]:
        response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Invalid email or password"


def test_registration_validation_hides_password(client: TestClient) -> None:
    response = client.post(f"{API}/auth/register", json={"email": "not-an-email", "password": "s3cr3t"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "s3cr3t" not in response.text  # submitted values are not echoed back


def test_login_is_rate_limited(client: TestClient) -> None:
    codes = [
        client.post(f"{API}/auth/login", json={"email": "x@example.com", "password": "nope"}).status_code
        for _ in range(12)
    ]
    assert codes[-1] == 429


def test_protected_routes_require_a_valid_token(client: TestClient) -> None:
    for path in ["/endpoints", "/incidents", "/dashboard/summary", "/auth/me"]:
        assert client.get(API + path).status_code == 401
    assert client.get(f"{API}/endpoints", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_expired_token_is_rejected(client: TestClient, auth: dict) -> None:
    settings = get_settings()
    me = client.get(f"{API}/auth/me", headers=auth).json()
    past = datetime.now(UTC) - timedelta(hours=2)
    token = jwt.encode(
        {"sub": me["id"], "iat": past, "exp": past + timedelta(minutes=5), "type": "access"},
        settings.jwt_secret,
        algorithm="HS256",
    )
    response = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "expired" in response.json()["error"]["message"].lower()


def test_token_signed_with_other_secret_is_rejected(client: TestClient, auth: dict) -> None:
    me = client.get(f"{API}/auth/me", headers=auth).json()
    forged = jwt.encode(
        {
            "sub": me["id"],
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "access",
        },
        "x" * 48,
        algorithm="HS256",
    )
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


# ---- endpoint CRUD ----------------------------------------------------------------------------


def test_endpoint_crud(client: TestClient, auth: dict) -> None:
    ep = create_endpoint(client, auth, name="Users API", interval_seconds=60, headers={"X-Api-Version": "2"})
    assert ep["health_status"] == "unknown" and ep["schema_status"] == "unknown"
    assert client.get(f"{API}/endpoints/{ep['id']}", headers=auth).json()["name"] == "Users API"

    updated = client.patch(
        f"{API}/endpoints/{ep['id']}", json={"name": "Users v2", "is_active": False}, headers=auth
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Users v2" and updated.json()["is_active"] is False

    assert client.delete(f"{API}/endpoints/{ep['id']}", headers=auth).status_code == 204
    assert client.get(f"{API}/endpoints/{ep['id']}", headers=auth).status_code == 404


def test_endpoint_validation(client: TestClient, auth: dict) -> None:
    bad_payloads = [
        {"name": "x", "url": "ftp://example.com/file"},
        {"name": "x", "url": "https://api.example.com", "interval_seconds": 5},
        {"name": "x", "url": "https://api.example.com", "timeout_seconds": 120},
        {"name": "x", "url": "https://api.example.com", "expected_status": 99},
        {"name": "x", "url": "https://api.example.com", "method": "DELETE"},
        {"name": "x", "url": "https://api.example.com", "headers": {"Host": "evil"}},
        {"name": "x", "url": "https://api.example.com", "headers": {"X-Forwarded-For": "1.2.3.4"}},
        {"name": "x", "url": "https://api.example.com", "headers": {"X-Bad": "a\r\nInjected: 1"}},
        {"name": "x", "url": "https://api.example.com", "owner_id": "00000000-0000-0000-0000-000000000000"},
        {"name": "", "url": "https://api.example.com"},
    ]
    for payload in bad_payloads:
        response = client.post(f"{API}/endpoints", json=payload, headers=auth)
        assert response.status_code == 422, payload


def test_ssrf_destinations_rejected_at_registration(client: TestClient, auth: dict) -> None:
    for url in [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8000/",
        "https://db.internal.test/",
        "https://gone.nxdomain.test/",
        "http://[::1]/",
    ]:
        response = client.post(f"{API}/endpoints", json={"name": "x", "url": url}, headers=auth)
        assert response.status_code == 422, url
        assert response.json()["error"]["code"] == "unsafe_url"


def test_ssrf_destinations_rejected_on_update(client: TestClient, auth: dict) -> None:
    ep = create_endpoint(client, auth)
    response = client.patch(
        f"{API}/endpoints/{ep['id']}", json={"url": "https://db.internal.test/"}, headers=auth
    )
    assert response.status_code == 422


def test_duplicate_name_conflicts(client: TestClient, auth: dict) -> None:
    create_endpoint(client, auth, name="same")
    response = client.post(
        f"{API}/endpoints", json={"name": "same", "url": "https://api.example.com/"}, headers=auth
    )
    assert response.status_code == 409


def test_null_fields_rejected_on_update(client: TestClient, auth: dict) -> None:
    ep = create_endpoint(client, auth)
    assert client.patch(f"{API}/endpoints/{ep['id']}", json={"url": None}, headers=auth).status_code == 422


def test_cross_user_access_is_denied(client: TestClient, auth: dict) -> None:
    ep = create_endpoint(client, auth)
    intruder = register(client)
    base = f"{API}/endpoints/{ep['id']}"
    assert client.get(base, headers=intruder).status_code == 404
    assert client.patch(base, json={"name": "pwned"}, headers=intruder).status_code == 404
    assert client.delete(base, headers=intruder).status_code == 404
    assert client.post(f"{base}/checks", headers=intruder).status_code == 404
    assert client.get(f"{base}/checks", headers=intruder).status_code == 404
    assert client.get(f"{base}/schema", headers=intruder).status_code == 404
    assert client.get(f"{base}/metrics", headers=intruder).status_code == 404
    accept = client.post(f"{base}/baseline", json={"check_id": ep["id"]}, headers=intruder)
    assert accept.status_code == 404
    assert client.get(f"{API}/endpoints", headers=intruder).json()["total"] == 0
    assert client.get(base, headers=auth).json()["name"] == ep["name"]  # untouched


def test_list_pagination_search_and_filters(client: TestClient, auth: dict) -> None:
    for i in range(5):
        create_endpoint(client, auth, name=f"service-{i}", is_active=i % 2 == 0)
    create_endpoint(client, auth, name="billing")

    page = client.get(f"{API}/endpoints", params={"page": 2, "page_size": 2}, headers=auth).json()
    assert page["total"] == 6 and len(page["items"]) == 2 and page["page"] == 2

    search = client.get(f"{API}/endpoints", params={"search": "BILL"}, headers=auth).json()
    assert [e["name"] for e in search["items"]] == ["billing"]

    paused = client.get(f"{API}/endpoints", params={"is_active": False}, headers=auth).json()
    assert paused["total"] == 2

    assert client.get(f"{API}/endpoints", params={"page_size": 1000}, headers=auth).status_code == 422
    assert client.get(f"{API}/endpoints", params={"health": "bogus"}, headers=auth).status_code == 422
