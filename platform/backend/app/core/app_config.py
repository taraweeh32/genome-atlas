"""B. APPLICATION CONFIGURATION.

Platform settings, limits, policies and feature configuration. Deliberately
separate from environment configuration (connections/secrets) and from
scientific configuration.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigurationError

API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLATFORM_", extra="ignore")

    api_prefix: str = API_PREFIX
    api_version: str = API_VERSION

    # Limits. Enforcement of dataset/file limits belongs to later packages; the
    # values live here so no module invents its own constant.
    max_upload_bytes: int = Field(default=50 * 1024 * 1024 * 1024, ge=1)
    max_page_size: int = Field(default=200, ge=1, le=1000)
    default_page_size: int = Field(default=25, ge=1, le=1000)

    # Policies (enforced by later packages, declared once here).
    default_result_retention_days: int = Field(default=365, ge=1)
    require_human_review_before_report: bool = True

    # Feature configuration.
    feature_openapi_docs: bool = True


@lru_cache(maxsize=1)
def get_application_settings() -> ApplicationSettings:
    try:
        settings = ApplicationSettings()
    except ValidationError as exc:  # pragma: no cover
        raise ConfigurationError(f"invalid application configuration: {exc}") from exc
    if settings.default_page_size > settings.max_page_size:
        raise ConfigurationError(
            "default page size cannot exceed max page size", key="PLATFORM_DEFAULT_PAGE_SIZE"
        )
    return settings
