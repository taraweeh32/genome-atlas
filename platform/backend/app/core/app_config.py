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


class SecurityPolicySettings(BaseSettings):
    """Security *policy* — application configuration, not secrets.

    Every value here is enforced by the backend. Nothing in this class is sent to
    the frontend as a security decision; the frontend may only render hints such
    as a minimum password length.
    """

    model_config = SettingsConfigDict(env_prefix="SECURITY_", extra="ignore")

    # --- sessions ------------------------------------------------------- #
    session_cookie_name: str = "gp_session"
    csrf_cookie_name: str = "gp_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    #: Idle timeout; refreshed by activity but never beyond the absolute limit.
    session_idle_minutes: int = Field(default=60, ge=5, le=24 * 60)
    #: Hard ceiling on session lifetime.
    session_absolute_hours: int = Field(default=12, ge=1, le=24 * 30)
    #: Re-authentication window for sensitive operations.
    reauthentication_window_minutes: int = Field(default=15, ge=1, le=240)
    max_active_sessions_per_user: int = Field(default=10, ge=1, le=100)

    # --- credentials ---------------------------------------------------- #
    password_min_length: int = Field(default=12, ge=12, le=128)
    password_require_symbol: bool = False
    max_failed_authentication_attempts: int = Field(default=5, ge=3, le=50)
    account_lockout_minutes: int = Field(default=15, ge=1, le=24 * 60)
    email_verification_ttl_hours: int = Field(default=48, ge=1, le=24 * 14)
    password_reset_ttl_minutes: int = Field(default=60, ge=5, le=24 * 60)
    invitation_ttl_hours: int = Field(default=168, ge=1, le=24 * 60)

    # --- policy --------------------------------------------------------- #
    #: An unverified account may not hold a normal session.
    require_email_verification_for_login: bool = True
    #: Privileged platform operations require a verified second factor. The MFA
    #: package supplies the factor; until then privileged operations are refused
    #: rather than silently allowed.
    require_mfa_for_platform_administration: bool = False
    #: Organization creation is a request that a platform administrator decides.
    organizations_require_platform_approval: bool = True

    # --- rate limiting -------------------------------------------------- #
    authentication_rate_limit_attempts: int = Field(default=10, ge=1, le=1000)
    authentication_rate_limit_window_seconds: int = Field(default=300, ge=10, le=3600)
    registration_rate_limit_attempts: int = Field(default=5, ge=1, le=1000)
    registration_rate_limit_window_seconds: int = Field(default=3600, ge=10, le=86400)
    #: Fail closed when the rate-limit backend is unavailable.
    rate_limit_fail_open: bool = False


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLATFORM_", extra="ignore")

    api_prefix: str = API_PREFIX
    api_version: str = API_VERSION

    # Limits. Declared once here so no module invents its own constant.
    max_upload_bytes: int = Field(default=50 * 1024 * 1024 * 1024, ge=1)
    max_page_size: int = Field(default=200, ge=1, le=1000)
    default_page_size: int = Field(default=25, ge=1, le=1000)

    # Transfer grants. Short-lived on purpose: a presigned URL is a temporary
    # permission to move bytes, never a durable capability over an artifact.
    upload_url_ttl_seconds: int = Field(default=900, ge=60, le=24 * 3600)
    download_url_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    # Policies (enforced by later packages, declared once here).
    default_result_retention_days: int = Field(default=365, ge=1)
    require_human_review_before_report: bool = True

    # Feature configuration.
    feature_openapi_docs: bool = True
    #: Enables the development/test signature scanner. It is refused in
    #: production-like environments regardless of this flag; with no scanner the
    #: platform reports ``unavailable`` and refuses to accept uploads, rather
    #: than treating unscanned bytes as clean.
    feature_development_file_scanner: bool = True

    # Durable job execution. One declaration for every worker and every job kind,
    # so operational behaviour is tuned per deployment instead of per call site.
    job_max_attempts: int = Field(default=3, ge=1, le=25)
    job_initial_backoff_seconds: int = Field(default=30, ge=1, le=3600)
    job_backoff_multiplier: int = Field(default=4, ge=1, le=10)
    job_max_backoff_seconds: int = Field(default=3600, ge=1, le=24 * 3600)
    #: How long a claim is honoured without a heartbeat, and how often a worker
    #: refreshes it. The interval must stay well below the lease.
    job_lease_seconds: int = Field(default=60, ge=10, le=3600)
    job_heartbeat_interval_seconds: int = Field(default=15, ge=1, le=600)
    job_stale_grace_seconds: int = Field(default=30, ge=0, le=3600)
    #: Wall-clock ceiling for one attempt.
    job_timeout_seconds: int = Field(default=3600, ge=30, le=24 * 3600)
    job_scientific_timeout_seconds: int = Field(default=6 * 3600, ge=60, le=7 * 24 * 3600)
    #: How long a soft-deleted analysis stays recoverable.
    analysis_retention_days: int = Field(default=30, ge=1, le=3650)
    #: Worker fleet shape. Application and scientific workers are the same runtime
    #: with different queues, never the same process pretending to be both.
    worker_application_queues: str = "default,import,validation,export,maintenance"
    worker_scientific_queues: str = "scientific"
    worker_scientific_enabled: bool = True
    worker_recovery_interval_seconds: int = Field(default=30, ge=5, le=3600)
    worker_schedule_interval_seconds: int = Field(default=60, ge=5, le=3600)

    security: SecurityPolicySettings = Field(default_factory=SecurityPolicySettings)

    @property
    def application_queue_names(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in self.worker_application_queues.split(",") if part.strip())

    @property
    def scientific_queue_names(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in self.worker_scientific_queues.split(",") if part.strip())


@lru_cache(maxsize=1)
def get_application_settings() -> ApplicationSettings:
    try:
        settings = ApplicationSettings()
    except ValidationError as exc:  # pragma: no cover
        raise ConfigurationError(f"invalid application configuration: {exc}") from exc
    if settings.security.session_idle_minutes > settings.security.session_absolute_hours * 60:
        raise ConfigurationError(
            "session idle timeout cannot exceed the absolute session lifetime",
            key="SECURITY_SESSION_IDLE_MINUTES",
        )
    if settings.job_heartbeat_interval_seconds >= settings.job_lease_seconds:
        raise ConfigurationError(
            "the heartbeat interval must be shorter than the job lease, "
            "otherwise every claim expires before it is refreshed",
            key="PLATFORM_JOB_HEARTBEAT_INTERVAL_SECONDS",
        )
    if not settings.application_queue_names:
        raise ConfigurationError(
            "an application worker must be given at least one queue",
            key="PLATFORM_WORKER_APPLICATION_QUEUES",
        )
    if settings.worker_scientific_enabled and not settings.scientific_queue_names:
        raise ConfigurationError(
            "the scientific worker fleet is enabled but has no queue",
            key="PLATFORM_WORKER_SCIENTIFIC_QUEUES",
        )
    if settings.default_page_size > settings.max_page_size:
        raise ConfigurationError(
            "default page size cannot exceed max page size", key="PLATFORM_DEFAULT_PAGE_SIZE"
        )
    return settings
