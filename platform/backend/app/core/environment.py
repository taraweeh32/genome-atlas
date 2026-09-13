"""A. ENVIRONMENT CONFIGURATION.

Deployment-supplied values: environment identity, connection strings, endpoints
and secrets. No application policy and no scientific configuration lives here.
"""

from __future__ import annotations

import enum
from functools import lru_cache

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigurationError


class Environment(str, enum.Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production_like(self) -> bool:
        return self in (Environment.STAGING, Environment.PRODUCTION)

    @property
    def exposes_diagnostics(self) -> bool:
        """Only non-production-like environments may return detailed diagnostics."""
        return not self.is_production_like


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_", extra="ignore")

    url: str = Field(min_length=1)
    pool_min_size: int = Field(default=1, ge=0)
    pool_max_size: int = Field(default=10, ge=1)
    statement_timeout_ms: int = Field(default=30_000, ge=1_000)

    @field_validator("url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must be a postgresql+asyncpg:// URL")
        return value


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    url: str = Field(min_length=1)
    socket_timeout_seconds: float = Field(default=2.0, gt=0)

    @field_validator("url")
    @classmethod
    def _require_redis_scheme(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must start with redis:// or rediss://")
        return value


class ObjectStorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OBJECT_STORAGE_", extra="ignore")

    endpoint_url: str | None = None
    region: str = "us-east-1"
    bucket: str = Field(min_length=1)
    access_key_id: str | None = None
    secret_access_key: str | None = None
    force_path_style: bool = True


class AnalyticsSettings(BaseSettings):
    """Parquet/DuckDB boundary configuration (see infrastructure/analytics)."""

    model_config = SettingsConfigDict(env_prefix="ANALYTICS_", extra="ignore")

    parquet_root: str = Field(min_length=1)
    duckdb_memory_limit: str = "2GB"
    duckdb_threads: int = Field(default=2, ge=1)


class TransportSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_", extra="ignore")

    cors_allowed_origins: str = ""
    max_request_body_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", extra="ignore")

    environment: Environment = Environment.DEVELOPMENT
    name: str = "genomic-platform"
    log_level: str = "INFO"

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)  # type: ignore[arg-type]
    redis: RedisSettings = Field(default_factory=RedisSettings)  # type: ignore[arg-type]
    object_storage: ObjectStorageSettings = Field(default_factory=ObjectStorageSettings)  # type: ignore[arg-type]
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)  # type: ignore[arg-type]
    transport: TransportSettings = Field(default_factory=TransportSettings)

    def assert_production_safe(self) -> None:
        """Reject configurations that are unsafe outside development."""
        if not self.environment.is_production_like:
            return
        if not self.object_storage.access_key_id or not self.object_storage.secret_access_key:
            raise ConfigurationError(
                "object storage credentials are required outside development",
                key="OBJECT_STORAGE_ACCESS_KEY_ID",
            )
        if not self.transport.cors_origin_list:
            raise ConfigurationError(
                "explicit CORS origins are required outside development",
                key="API_CORS_ALLOWED_ORIGINS",
            )


@lru_cache(maxsize=1)
def get_environment_settings() -> EnvironmentSettings:
    try:
        settings = EnvironmentSettings()
    except ValidationError as exc:  # pragma: no cover - exercised via tests
        raise ConfigurationError(f"invalid environment configuration: {exc}") from exc
    settings.assert_production_safe()
    return settings
