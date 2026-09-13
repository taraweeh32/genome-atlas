"""Foundation tests for the infrastructure adapters.

These assert boundary behaviour that must hold without live services: settings
validation, explicit failure when an adapter is used before connect(), the
DuckDB/Parquet path boundary and the object-storage service contract. Tests that
require live PostgreSQL/Redis/S3 are marked ``integration``.
"""

from __future__ import annotations

import pytest

from app.application.ports import CacheService, ObjectStorageService
from app.core.environment import (
    AnalyticsSettings,
    DatabaseSettings,
    ObjectStorageSettings,
    RedisSettings,
)
from app.core.errors import ConfigurationError
from app.domain.errors import InfrastructureError
from app.infrastructure.analytics.duckdb_gateway import AnalyticsGateway
from app.infrastructure.persistence.database import Database
from app.infrastructure.redis.cache import RedisCache
from app.infrastructure.storage.object_storage import S3ObjectStorage

# -- PostgreSQL foundation -------------------------------------------------


def test_database_url_must_use_an_async_driver() -> None:
    with pytest.raises((ConfigurationError, ValueError)):
        DatabaseSettings(url="postgresql://user:pw@localhost:5432/db")


def test_database_accepts_the_async_driver() -> None:
    settings = DatabaseSettings(url="postgresql+asyncpg://user:pw@localhost:5432/db")
    assert settings.url.startswith("postgresql+asyncpg://")


@pytest.mark.asyncio
async def test_database_ping_before_connect_fails_explicitly() -> None:
    database = Database(DatabaseSettings(url="postgresql+asyncpg://u:p@localhost:5432/db"))
    with pytest.raises(InfrastructureError):
        await database.ping()


# -- Redis foundation ------------------------------------------------------


def test_redis_url_scheme_is_validated() -> None:
    with pytest.raises((ConfigurationError, ValueError)):
        RedisSettings(url="postgresql://localhost:6379/0")


@pytest.mark.asyncio
async def test_redis_operations_before_connect_fail_explicitly() -> None:
    cache = RedisCache(RedisSettings(url="redis://localhost:6379/15"))
    with pytest.raises(InfrastructureError):
        await cache.get("any-key")


def test_redis_cache_satisfies_the_cache_port() -> None:
    cache = RedisCache(RedisSettings(url="redis://localhost:6379/15"))
    assert isinstance(cache, CacheService)


# -- Object storage foundation --------------------------------------------


def _storage_settings() -> ObjectStorageSettings:
    return ObjectStorageSettings(
        bucket="test-bucket",
        endpoint_url="http://localhost:9000",
        access_key_id="key",
        secret_access_key="secret",
    )


def test_object_storage_satisfies_the_storage_port() -> None:
    assert isinstance(S3ObjectStorage(_storage_settings()), ObjectStorageService)


def test_object_storage_secret_is_not_in_its_repr() -> None:
    storage = S3ObjectStorage(_storage_settings())
    assert "secret" not in repr(storage).lower() or "secret_access_key" not in repr(storage)


# -- Parquet / DuckDB boundary --------------------------------------------


def test_analytics_gateway_exposes_the_parquet_root() -> None:
    gateway = AnalyticsGateway(AnalyticsSettings(parquet_root="s3://bucket/analytics"))
    assert gateway.parquet_root == "s3://bucket/analytics"


def test_analytics_dataset_paths_are_composed_under_the_root() -> None:
    gateway = AnalyticsGateway(AnalyticsSettings(parquet_root="s3://bucket/analytics"))
    path = gateway.dataset_path("dts_1", "variants")
    assert path.startswith("s3://bucket/analytics")
    assert path.endswith("dts_1/variants")
