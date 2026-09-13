"""C. SCIENTIFIC CONFIGURATION.

Describes how the application reaches the independently deployed scientific
compute subsystem. It never describes scientific algorithms.
"""

from __future__ import annotations

import enum
from functools import lru_cache

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.environment import Environment, get_environment_settings
from app.core.errors import ConfigurationError


class ScientificAdapterKind(str, enum.Enum):
    HTTP = "http"
    DEVELOPMENT = "development"


class ScientificSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCIENTIFIC_", extra="ignore")

    adapter: ScientificAdapterKind = ScientificAdapterKind.DEVELOPMENT
    service_base_url: str | None = None
    service_token: str | None = None
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    required_for_readiness: bool = False

    def validate_for(self, environment: Environment) -> None:
        if self.adapter is ScientificAdapterKind.DEVELOPMENT:
            if environment is Environment.PRODUCTION:
                raise ConfigurationError(
                    "the development scientific adapter must never be enabled in production",
                    key="SCIENTIFIC_ADAPTER",
                )
            return
        if not self.service_base_url:
            raise ConfigurationError(
                "the http scientific adapter requires a service base URL",
                key="SCIENTIFIC_SERVICE_BASE_URL",
            )
        if environment.is_production_like and not self.service_token:
            raise ConfigurationError(
                "the scientific service token is required outside development",
                key="SCIENTIFIC_SERVICE_TOKEN",
            )


@lru_cache(maxsize=1)
def get_scientific_settings() -> ScientificSettings:
    try:
        settings = ScientificSettings()
    except ValidationError as exc:  # pragma: no cover
        raise ConfigurationError(f"invalid scientific configuration: {exc}") from exc
    settings.validate_for(get_environment_settings().environment)
    return settings
