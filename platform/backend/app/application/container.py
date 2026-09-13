"""Dependency/service wiring.

A single explicit composition root. Nothing else constructs infrastructure
clients, so lifecycle (startup/shutdown) has exactly one owner.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.ports import HealthProbe
from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.core.app_config import ApplicationSettings, get_application_settings
from app.core.environment import EnvironmentSettings, get_environment_settings
from app.core.logging import get_logger
from app.core.scientific_config import ScientificSettings, get_scientific_settings
from app.infrastructure.analytics.duckdb_gateway import AnalyticsGateway
from app.infrastructure.observability.health import (
    ObjectStorageHealthProbe,
    PostgresHealthProbe,
    RedisHealthProbe,
    ScientificHealthProbe,
)
from app.infrastructure.persistence.database import Database
from app.infrastructure.redis.cache import RedisCache
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

    @classmethod
    def build(cls) -> Container:
        environment = get_environment_settings()
        application = get_application_settings()
        scientific_settings = get_scientific_settings()

        return cls(
            environment=environment,
            application=application,
            scientific_settings=scientific_settings,
            database=Database(environment.database),
            cache=RedisCache(environment.redis),
            object_storage=S3ObjectStorage(environment.object_storage),
            analytics=AnalyticsGateway(environment.analytics),
            scientific=build_scientific_gateway(scientific_settings, environment.environment),
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

    def get_readiness(self) -> GetReadiness:
        return GetReadiness(self.health_probes())

    def describe_scientific_capabilities(self) -> DescribeScientificCapabilities:
        return DescribeScientificCapabilities(self.scientific)
