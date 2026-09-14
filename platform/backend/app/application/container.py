"""Dependency/service wiring.

A single explicit composition root. Nothing else constructs infrastructure
clients, so lifecycle (startup/shutdown) has exactly one owner.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.ports import HealthProbe
from app.application.services.authorization import AuthorizationService
from app.application.services.sessions import SessionService
from app.application.use_cases.analysis.dependencies import AnalysisServices
from app.application.use_cases.data.dependencies import DataServices
from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.application.use_cases.identity.dependencies import IdentityServices
from app.application.use_cases.query.dependencies import QueryServices
from app.application.use_cases.results.dependencies import ResultServices
from app.application.use_cases.tenancy.dependencies import TenancyServices
from app.core.app_config import ApplicationSettings, get_application_settings
from app.core.environment import EnvironmentSettings, get_environment_settings
from app.core.logging import get_logger
from app.core.scientific_config import ScientificSettings, get_scientific_settings
from app.domain.analysis.policies import LeasePolicy, RetryPolicy, TimeoutPolicy
from app.domain.authorization.policy import AuthorizationPolicy
from app.domain.identity.passwords import PasswordPolicy
from app.domain.value_objects.enums import JobKind
from app.infrastructure.analytics.duckdb_gateway import AnalyticsGateway
from app.infrastructure.analytics.query_engine import DuckDbQueryEngine
from app.infrastructure.analytics.result_reader import DuckDbResultReader
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
from app.infrastructure.storage.checksums import StreamingChecksumService
from app.infrastructure.storage.inspection import StreamingFileInspector
from app.infrastructure.storage.object_storage import S3ObjectStorage
from app.infrastructure.storage.scanner import build_scanner
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

    def data_services(self) -> DataServices:
        """Dataset/upload/import/validation dependencies.

        The scanner is chosen by environment: a stand-in is never selected in a
        production-like deployment, so a missing real scanner surfaces as
        "unavailable" — which blocks acceptance — instead of silently passing.
        """
        return DataServices(
            unit_of_work=self.unit_of_work,
            clock=self.clock,
            authorization=self.authorization,
            storage=self.object_storage,
            scanner=build_scanner(
                environment=self.environment.environment,
                storage=self.object_storage,
                enabled=self.application.feature_development_file_scanner,
            ),
            inspector=StreamingFileInspector(self.object_storage),
            checksums=StreamingChecksumService(self.object_storage),
            config=self.application,
            storage_provider="s3",
            storage_bucket=self.environment.object_storage.bucket,
            upload_url_ttl_seconds=self.application.upload_url_ttl_seconds,
            download_url_ttl_seconds=self.application.download_url_ttl_seconds,
        )

    def analysis_services(self) -> AnalysisServices:
        """Analysis/execution/job/schedule dependencies.

        The retry, lease and timeout policies come from configuration rather than
        from each call site, so operational behaviour is tunable per deployment
        and identical for every job kind.
        """
        return AnalysisServices(
            unit_of_work=self.unit_of_work,
            clock=self.clock,
            authorization=self.authorization,
            config=self.application,
            scientific=self.scientific,
            retry=RetryPolicy(
                max_attempts=self.application.job_max_attempts,
                initial_backoff_seconds=self.application.job_initial_backoff_seconds,
                backoff_multiplier=self.application.job_backoff_multiplier,
                max_backoff_seconds=self.application.job_max_backoff_seconds,
            ),
            lease=LeasePolicy(
                lease_seconds=self.application.job_lease_seconds,
                heartbeat_interval_seconds=self.application.job_heartbeat_interval_seconds,
                stale_grace_seconds=self.application.job_stale_grace_seconds,
            ),
            timeouts=TimeoutPolicy(
                default_seconds=self.application.job_timeout_seconds,
                per_kind_seconds={
                    JobKind.SCIENTIFIC_EXECUTION.value: (
                        self.application.job_scientific_timeout_seconds
                    ),
                    JobKind.ANALYSIS_EXECUTION.value: (
                        self.application.job_scientific_timeout_seconds
                    ),
                },
            ),
            retention_days=self.application.analysis_retention_days,
        )

    def result_services(self) -> ResultServices:
        """Scientific data-layer dependencies.

        The analytical reader, object storage and checksum service are all here
        because making a result surface available means *verifying* it: reading
        what the file actually contains and checking the bytes against what the
        producer declared.
        """
        return ResultServices(
            unit_of_work=self.unit_of_work,
            clock=self.clock,
            authorization=self.authorization,
            config=self.application,
            analytics=DuckDbResultReader(self.analytics),
            checksums=StreamingChecksumService(self.object_storage),
            object_storage=self.object_storage,
            download_url_seconds=self.application.download_url_ttl_seconds,
        )

    def query_services(self) -> QueryServices:
        """Filtering, ranking and view dependencies.

        The analytical query engine is wired here because filtering executes
        against the Package 6 Parquet surfaces through the same boundary; there is
        no second analytical store.
        """
        return QueryServices(
            unit_of_work=self.unit_of_work,
            clock=self.clock,
            authorization=self.authorization,
            config=self.application,
            query_engine=DuckDbQueryEngine(self.analytics),
        )

    def get_readiness(self) -> GetReadiness:
        return GetReadiness(self.health_probes())

    def describe_scientific_capabilities(self) -> DescribeScientificCapabilities:
        return DescribeScientificCapabilities(self.scientific)
