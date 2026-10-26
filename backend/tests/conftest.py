"""Test fixtures.

Databases: SQLite file + mongomock by default (no services needed). Set TEST_DATABASE_URL /
TEST_MONGO_URL to run the same suite against real PostgreSQL / MongoDB (CI does this).
Outbound HTTP: every test uses httpx.MockTransport via `upstream`; nothing reaches the Internet.
"""

import os
import secrets
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

import httpx
import mongomock
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.api import deps
from app.database.sql import Base, build_engine, get_db
from app.main import create_app
from app.monitoring.http_client import SafeHTTPClient
from app.repositories.documents import DocumentStore
from app.security.ssrf import DestinationPolicy
from app.services.monitoring_service import MonitoringService

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(scope="session")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        url = f"sqlite:///{Path(tmp_path_factory.mktemp('db')) / 'test.db'}"
    eng = build_engine(url)
    if eng.dialect.name == "sqlite":

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> Iterator[sessionmaker[Session]]:
    yield sessionmaker(bind=engine, expire_on_commit=False)
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            names = ", ".join(t.name for t in Base.metadata.sorted_tables)
            conn.execute(text(f"TRUNCATE {names} CASCADE"))
        else:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture
def mongo_db() -> Iterator:
    url = os.environ.get("TEST_MONGO_URL")
    client = MongoClient(url, tz_aware=True) if url else mongomock.MongoClient(tz_aware=True)
    db = client[f"driftradar_test_{uuid.uuid4().hex[:8]}"]
    yield db
    client.drop_database(db.name)


@pytest.fixture
def docs(mongo_db) -> DocumentStore:
    return DocumentStore(mongo_db)


class Upstream:
    """Programmable fake for monitored APIs: set responses per URL, inspect requests."""

    def __init__(self) -> None:
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[httpx.Request] = []

    def json(self, url: str, body: object, status: int = 200) -> None:
        self.routes[url] = lambda _req: httpx.Response(status, json=body)

    def respond(self, url: str, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.routes[url] = handler

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get(str(request.url))
        if handler is None:
            raise httpx.ConnectError("no route", request=request)
        return handler(request)


def fake_resolver(host: str, port: int) -> list[str]:
    """Deterministic DNS: *.internal.test resolves privately, everything else publicly."""
    if host.endswith("internal.test"):
        return ["10.0.0.5"]
    if host.endswith("nxdomain.test"):
        raise OSError("Name or service not known")
    return [PUBLIC_IP]


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def policy() -> DestinationPolicy:
    return DestinationPolicy(resolver=fake_resolver)


@pytest.fixture
def monitor(
    session_factory, upstream: Upstream, docs: DocumentStore, policy: DestinationPolicy
) -> MonitoringService:
    http = SafeHTTPClient(
        policy,
        max_response_bytes=64_000,
        max_retries=1,
        transport=httpx.MockTransport(upstream.handle),
        retry_backoff_seconds=0,
    )
    return MonitoringService(session_factory, http, docs)


@pytest.fixture
def client(
    session_factory,
    docs: DocumentStore,
    policy: DestinationPolicy,
    monitor: MonitoringService,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("MANUAL_CHECK_COOLDOWN_SECONDS", "0")
    deps.get_settings.cache_clear()
    app = create_app()

    def _db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[deps.get_document_store] = lambda: docs
    app.dependency_overrides[deps.get_destination_policy] = lambda: policy
    app.dependency_overrides[deps.get_monitoring_service] = lambda: monitor
    with TestClient(app) as test_client:
        yield test_client
    deps.get_settings.cache_clear()


def register(
    client: TestClient, email: str | None = None, password: str = "correct-horse-battery"
) -> dict[str, str]:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    return register(client)


def create_endpoint(client: TestClient, auth: dict[str, str], **overrides: object) -> dict:
    payload = {"name": f"ep-{uuid.uuid4().hex[:6]}", "url": "https://api.example.com/users/1", **overrides}
    response = client.post("/api/v1/endpoints", json=payload, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def run_check(client: TestClient, auth: dict[str, str], endpoint_id: str) -> dict:
    response = client.post(f"/api/v1/endpoints/{endpoint_id}/checks", headers=auth)
    assert response.status_code == 201, response.text
    return response.json()
