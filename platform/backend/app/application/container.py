"""Dependency/service wiring.

A single explicit composition root. Nothing else constructs infrastructure
clients, so lifecycle (startup/shutdown) has exactly one owner.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.ports import HealthProbe
from app.application.services.authorization import AuthorizationService
from app.application.services.sessions import SessionService
from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.application.use_cases.identity.dependencies import IdentityServices
from app.application.use_cases.tenancy.dependencies import TenancyServices
from app.core.app_config import ApplicationSettings, get_application_settings
from app.core.environment import EnvironmentSettings, get_environment_settings
from app.core.logging import get_logger
from app.core.scientific_config import ScientificSettings, get_scientific_settings
from app.domain.authorization.policy import AuthorizationPolicy
from app.domain.identity.passwords import PasswordPolicy
from app.infrastructure.analytics.duckdb_gateway import AnalyticsGateway
from app.infrastructure.observability.health import (
    ObjectStorageHealthProbe,
    PostgresHealthProbe,
    RedisHealthProbe,
    ScientificHealthProbe,
)
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.unit_of_work import SqlUnitOfWorkFactory
from app.infrastructure.redis.cache import RedisCache
from app.infrastructure.redis.rate_limiter import RedisRateLimiter
from app.infrastructure.security.clock import SystemClock
from app.infrastructure.security.passwords import Argon2PasswordHasher
from app.infrastructure.security.tokens import TokenHasher
from app.infrastructure.storage.object_storage import S3ObjectStorage
from app.scientific.adapters.factory import build_scientific_gateway
from app.scientific.contracts import ScientificEngineGateway

logger = get_logger(__name__)


@dataclass
class Container:
    """Holds process-wide services and the use cases built from them."""

    environment: EnvironmentSettings
    application: ApplicationSettings
    scientific_settings: ScientificSettings

    database: Database
    cache: RedisCache
    object_storage: S3ObjectStorage
    analytics: AnalyticsGateway
    scientific: ScientificEngineGateway

    #: Security services. Constructed once: hashing parameters and the token
    #: pepper are deployment configuration, not per-request state.
    clock: SystemClock
    passwords: Argon2PasswordHasher
    tokens: TokenHasher
    unit_of_work: SqlUnitOfWorkFactory
    authorization: AuthorizationService
    sessions: SessionService

    @classmethod
    def build(cls) -> Container:
        environment = get_environment_settings()
        application = get_application_settings()
        scientific_settings = get_scientific_settings()

        authentication = environment.authentication
        if authentication.token_pepper:
            pepper = authentication.token_pepper
        else:
            # Development-only fallback so a fresh checkout runs; production-like
            # environments are rejected by ``assert_production_safe``.
            pepper = "development-only-token-pepper"
        database = Database(environment.database)
        security_policy = application.security

        return cls(
            environment=environment,
            application=application,
            scientific_settings=scientific_settings,
            database=database,
            cache=RedisCache(environment.redis),
            object_storage=S3ObjectStorage(environment.object_storage),
            analytics=AnalyticsGateway(environment.analytics),
            scientific=build_scientific_gateway(scientific_settings, environment.environment),
            clock=SystemClock(),
            passwords=Argon2PasswordHasher(
                time_cost=authentication.password_hash_time_cost,
                memory_cost_kib=authentication.password_hash_memory_kib,
                parallelism=authentication.password_hash_parallelism,
            ),
            tokens=TokenHasher(pepper),
            unit_of_work=SqlUnitOfWorkFactory(database),
            authorization=AuthorizationService(AuthorizationPolicy()),
            sessions=SessionService(
                token_hasher=TokenHasher(pepper),
                clock=SystemClock(),
                policy=security_policy,
            ),
        )

    # -- lifecycle ---------------------------------------------------------

    async def startup(self) -> None:
        logger.info("container startup", extra={"environment": self.environment.environment.value})
        await self.database.connect()
        await self.cache.connect()
        await self.object_storage.connect()

    async def shutdown(self) -> None:
        """Best-effort, order-reversed teardown. One failure must not skip the rest."""
        for name, closer in (
            ("object_storage", self.object_storage.close),
            ("cache", self.cache.close),
            ("database", self.database.close),
            ("scientific", self.scientific.close),
        ):
            try:
                await closer()
            except Exception:
                logger.warning("shutdown step failed", extra={"component": name}, exc_info=True)
        logger.info("container shutdown complete")

    # -- wiring ------------------------------------------------------------

    def health_probes(self) -> tuple[HealthProbe, ...]:
        return (
            PostgresHealthProbe(self.database),
            RedisHealthProbe(self.cache),
            ObjectStorageHealthProbe(self.object_storage),
            ScientificHealthProbe(
                self.scientific, required=self.scientific_settings.required_for_readiness
            ),
        )

    # -- security / identity wiring ---------------------------------------

    def rate_limiter(self) -> RedisRateLimiter:
        """Built per call: it borrows the live Redis client owned by the cache."""
        return RedisRateLimiter(
            self.cache.raw_client(),
            fail_open=self.application.security.rate_limit_fail_open,
        )

    def _password_policy(self) -> PasswordPolicy:
        policy = self.application.security
        return PasswordPolicy(
            min_length=policy.password_min_length,
            require_symbol=policy.password_require_symbol,
        )

    def identity_services(self) -> IdentityServices:
        return IdentityServices(
            unit_of_work=self.unit_of_work,
            clock=self.clock,
            passwords=self.passwords,
            tokens=self.tokens,
            sessions=self.sessions,
            authorization=self.authorization,
            rate_limiter=self.rate_limiter(),
            policy=self.application.security,
            password_policy=self._password_policy(),
            expose_development_tokens=self.environment.environment.exposes_diagnostics,
        )

    def tenancy_services(self) -> TenancyServices:
        return TenancyServices(
            unit_of_work=self.unit_of_work,
            clock=self.clock,
            tokens=self.tokens,
            authorization=self.authorization,
            policy=self.application.security,
            expose_development_tokens=self.environment.environment.exposes_diagnostics,
        )

    def get_readiness(self) -> GetReadiness:
        return GetReadiness(self.health_probes())

    def describe_scientific_capabilities(self) -> DescribeScientificCapabilities:
        return DescribeScientificCapabilities(self.scientific)
