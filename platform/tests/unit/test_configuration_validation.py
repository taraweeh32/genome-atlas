"""Configuration validation must fail loudly rather than pick unsafe defaults."""

from __future__ import annotations

import pytest

from app.core.app_config import ApplicationSettings, get_application_settings
from app.core.environment import (
    DatabaseSettings,
    Environment,
    EnvironmentSettings,
    RedisSettings,
    TransportSettings,
)
from app.core.errors import ConfigurationError
from app.core.scientific_config import (
    ScientificAdapterKind,
    ScientificSettings,
    get_scientific_settings,
)


def _settings(**overrides: object) -> EnvironmentSettings:
    base: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "database": DatabaseSettings(url="postgresql+asyncpg://u:p@db:5432/app"),
        "redis": RedisSettings(url="redis://cache:6379/0"),
        "transport": TransportSettings(cors_allowed_origins="https://app.example.com"),
    }
    base.update(overrides)
    return EnvironmentSettings.model_validate(base)


class TestDatabaseSettings:
    def test_rejects_non_async_driver(self) -> None:
        with pytest.raises(ValueError, match="asyncpg"):
            DatabaseSettings(url="postgresql://u:p@db:5432/app")

    def test_accepts_async_driver(self) -> None:
        assert DatabaseSettings(url="postgresql+asyncpg://u:p@db:5432/app").url.endswith("/app")


class TestRedisSettings:
    def test_rejects_foreign_scheme(self) -> None:
        with pytest.raises(ValueError, match="redis://"):
            RedisSettings(url="postgresql://u:p@db:5432/app")


class TestProductionSafety:
    def test_missing_object_storage_credentials_is_rejected(self) -> None:
        settings = _settings()
        settings.object_storage.access_key_id = None
        with pytest.raises(ConfigurationError) as excinfo:
            settings.assert_production_safe()
        assert excinfo.value.key == "OBJECT_STORAGE_ACCESS_KEY_ID"

    def test_wildcard_absent_cors_is_rejected(self) -> None:
        settings = _settings(transport=TransportSettings(cors_allowed_origins=""))
        settings.object_storage.access_key_id = "key"
        settings.object_storage.secret_access_key = "secret"
        with pytest.raises(ConfigurationError) as excinfo:
            settings.assert_production_safe()
        assert excinfo.value.key == "API_CORS_ALLOWED_ORIGINS"

    def test_development_is_not_subject_to_production_rules(self) -> None:
        settings = _settings(environment=Environment.DEVELOPMENT)
        settings.assert_production_safe()  # must not raise


class TestScientificConfiguration:
    def test_development_adapter_is_refused_in_production(self) -> None:
        settings = ScientificSettings(adapter=ScientificAdapterKind.DEVELOPMENT)
        with pytest.raises(ConfigurationError, match="never be enabled in production"):
            settings.validate_for(Environment.PRODUCTION)

    def test_development_adapter_is_allowed_in_development(self) -> None:
        ScientificSettings(adapter=ScientificAdapterKind.DEVELOPMENT).validate_for(
            Environment.DEVELOPMENT
        )

    def test_http_adapter_requires_base_url(self) -> None:
        settings = ScientificSettings(adapter=ScientificAdapterKind.HTTP)
        with pytest.raises(ConfigurationError) as excinfo:
            settings.validate_for(Environment.DEVELOPMENT)
        assert excinfo.value.key == "SCIENTIFIC_SERVICE_BASE_URL"

    def test_http_adapter_requires_token_outside_development(self) -> None:
        settings = ScientificSettings(
            adapter=ScientificAdapterKind.HTTP, service_base_url="https://sci.internal"
        )
        with pytest.raises(ConfigurationError) as excinfo:
            settings.validate_for(Environment.STAGING)
        assert excinfo.value.key == "SCIENTIFIC_SERVICE_TOKEN"


class TestApplicationSettings:
    def test_default_page_size_may_not_exceed_max(
        self, monkeypatch: pytest.MonkeyPatch, clear_settings_cache: None
    ) -> None:
        monkeypatch.setenv("PLATFORM_MAX_PAGE_SIZE", "10")
        monkeypatch.setenv("PLATFORM_DEFAULT_PAGE_SIZE", "50")
        with pytest.raises(ConfigurationError, match="default page size"):
            get_application_settings()

    def test_api_prefix_is_versioned(self) -> None:
        assert ApplicationSettings().api_prefix == "/api/v1"


class TestSettingsSeparation:
    def test_environment_settings_carry_no_scientific_fields(self) -> None:
        assert "adapter" not in EnvironmentSettings.model_fields

    def test_scientific_settings_carry_no_connection_strings(
        self, clear_settings_cache: None
    ) -> None:
        fields = set(get_scientific_settings().model_fields)
        assert not fields & {"database", "redis", "object_storage"}
