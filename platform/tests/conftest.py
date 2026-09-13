"""Shared test fixtures.

Unit/domain/application/API tests run without live infrastructure: the API test
app is built with stubbed infrastructure so that transport, error mapping,
readiness aggregation and wiring are genuinely exercised. Tests marked
``integration`` require the compose stack.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

REQUIRED_TEST_ENV = {
    "APP_ENVIRONMENT": "test",
    "APP_LOG_LEVEL": "WARNING",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
    "REDIS_URL": "redis://localhost:6379/15",
    "OBJECT_STORAGE_BUCKET": "test-bucket",
    "OBJECT_STORAGE_ENDPOINT_URL": "http://localhost:9000",
    "OBJECT_STORAGE_ACCESS_KEY_ID": "test-key",
    "OBJECT_STORAGE_SECRET_ACCESS_KEY": "test-secret",
    "ANALYTICS_PARQUET_ROOT": "s3://test-bucket/analytics",
    "API_CORS_ALLOWED_ORIGINS": "http://localhost:3000",
    "SCIENTIFIC_ADAPTER": "development",
}


@pytest.fixture(autouse=True, scope="session")
def _test_environment() -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in REQUIRED_TEST_ENV}
    os.environ.update(REQUIRED_TEST_ENV)
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def clear_settings_cache() -> Iterator[None]:
    """Settings are cached per process; tests that mutate env must clear them."""
    from app.core import app_config, environment, scientific_config

    for getter in (
        environment.get_environment_settings,
        app_config.get_application_settings,
        scientific_config.get_scientific_settings,
    ):
        getter.cache_clear()
    yield
    for getter in (
        environment.get_environment_settings,
        app_config.get_application_settings,
        scientific_config.get_scientific_settings,
    ):
        getter.cache_clear()
