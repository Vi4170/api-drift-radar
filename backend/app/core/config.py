"""Application settings loaded from environment variables (see backend/.env.example)."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"

    # Databases
    database_url: str = "postgresql+psycopg://driftradar:driftradar@localhost:5432/driftradar"
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "driftradar"
    snapshot_retention_days: int = Field(default=14, ge=1, le=365)

    # Auth. No default secret: the app refuses to start without a strong one.
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=5, le=24 * 60)

    # HTTP API
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    login_rate_limit_per_minute: int = Field(default=10, ge=1)
    manual_check_cooldown_seconds: int = Field(default=10, ge=0)

    # Outbound monitoring safeguards
    monitor_max_response_bytes: int = Field(default=1_048_576, ge=1024, le=10 * 1_048_576)
    monitor_max_retries: int = Field(default=1, ge=0, le=3)
    monitor_max_concurrency: int = Field(default=5, ge=1, le=50)
    monitor_min_interval_seconds: int = Field(default=30, ge=5)
    monitor_max_timeout_seconds: float = Field(default=30.0, gt=0, le=60)
    monitor_user_agent: str = "APIDriftRadar/1.0 (+schema-monitor)"
    # DEMO/DEV ONLY: exact hostnames exempt from the public-IP check (e.g. "mock-api").
    monitor_allowed_hosts: Annotated[list[str], NoDecode] = []

    # Worker
    worker_reconcile_seconds: int = Field(default=30, ge=5)

    @field_validator("cors_origins", "monitor_allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("monitor_allowed_hosts")
    @classmethod
    def _lower_hosts(cls, value: list[str]) -> list[str]:
        return [host.lower().rstrip(".") for host in value]

    @field_validator("jwt_secret")
    @classmethod
    def _reject_placeholder(cls, value: str) -> str:
        if "change-me" in value.lower():
            raise ValueError("JWT_SECRET still contains the placeholder value; generate a real secret")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
