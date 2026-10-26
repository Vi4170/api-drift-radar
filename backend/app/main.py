import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_document_store
from app.api.routes import auth, endpoints, incidents
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.database.sql import get_engine
from app.security.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    store = app.dependency_overrides.get(get_document_store, get_document_store)()
    try:
        store.ensure_indexes(settings.snapshot_retention_days)
    except PyMongoError:
        # Start anyway: checks are still recorded (schema_status=unavailable) and /readyz reports it.
        logger.warning("MongoDB unavailable at startup; indexes will be created on next start")
    yield


def create_app() -> FastAPI:
    """App factory (run with `uvicorn app.main:create_app --factory`)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="API Drift Radar",
        version="1.0.0",
        description="Monitor HTTP APIs, detect JSON schema drift and manage incidents.",
        lifespan=lifespan,
    )
    app.state.auth_limiter = RateLimiter(settings.login_rate_limit_per_minute, 60)
    app.state.check_limiter = RateLimiter(30, 60)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(auth.router)
    api.include_router(endpoints.router)
    api.include_router(incidents.router)
    app.include_router(api)

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    def readyz() -> JSONResponse:
        """Readiness: both databases reachable."""
        checks = {"postgres": False, "mongodb": get_document_store().ping()}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["postgres"] = True
        except SQLAlchemyError:
            pass
        ok = all(checks.values())
        return JSONResponse({"status": "ok" if ok else "degraded", **checks}, status_code=200 if ok else 503)

    return app
