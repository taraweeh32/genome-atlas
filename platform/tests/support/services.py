"""Wiring for use-case tests.

Real security services (Argon2, token hashing, session service, authorization
policy) run against in-memory repositories, so the tests exercise the actual
rules rather than a simplified re-implementation of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.services.authorization import AuthorizationService
from app.domain.authorization.policy import AuthorizationPolicy
from app.application.services.context import RequestContext
from app.application.services.sessions import SessionService
from app.core.app_config import ApplicationSettings, SecurityPolicySettings
from app.application.use_cases.identity.dependencies import IdentityServices
from app.application.use_cases.data.dependencies import DataServices
from app.application.use_cases.tenancy.dependencies import TenancyServices
from app.application.use_cases.analysis.dependencies import AnalysisServices
from app.application.use_cases.results.dependencies import ResultServices
from app.core.environment import Environment
from app.scientific.adapters.development import DevelopmentScientificAdapter
from app.domain.identity.passwords import PasswordPolicy
from app.infrastructure.security.clock import FixedClock
from app.infrastructure.security.passwords import Argon2PasswordHasher
from app.infrastructure.security.tokens import TokenHasher
from tests.support.analytics import StubAnalyticalReader
from tests.support.data_storage import (
    MemoryObjectStorage,
    StubChecksums,
    StubInspector,
    StubScanner,
)
from tests.support.memory import (
    AllowAllRateLimiter,
    MemoryRepositories,
    MemoryUnitOfWorkFactory,
)

#: A fixed moment keeps expiry assertions exact rather than time-dependent.
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

STRONG_PASSWORD = "Correct-Horse-Battery-9"
OTHER_PASSWORD = "Another-Strong-Passphrase-4"


@dataclass
class Harness:
    repositories: MemoryRepositories
    unit_of_work: MemoryUnitOfWorkFactory
    clock: FixedClock
    identity: IdentityServices
    tenancy: TenancyServices
    authorization: AuthorizationService
    sessions: SessionService
    tokens: TokenHasher
    policy: SecurityPolicySettings
    request: RequestContext
    data: DataServices
    storage: MemoryObjectStorage
    scanner: StubScanner
    analysis: AnalysisServices
    scientific: DevelopmentScientificAdapter
    results: ResultServices
    analytics: StubAnalyticalReader

    def advance_to(self, moment: datetime) -> None:
        self.clock._moment = moment  # noqa: SLF001 - test clock


def build_harness(
    *,
    policy: SecurityPolicySettings | None = None,
    expose_development_tokens: bool = True,
) -> Harness:
    policy = policy or SecurityPolicySettings()
    repositories = MemoryRepositories()
    unit_of_work = MemoryUnitOfWorkFactory(repositories)
    clock = FixedClock(NOW)
    tokens = TokenHasher(pepper="test-pepper")
    # Deliberately cheap Argon2 parameters: these tests assert behaviour, not
    # hashing cost. Production parameters come from deployment configuration.
    passwords = Argon2PasswordHasher(time_cost=1, memory_cost_kib=8192, parallelism=1)
    authorization = AuthorizationService(AuthorizationPolicy())
    sessions = SessionService(token_hasher=tokens, clock=clock, policy=policy)
    identity = IdentityServices(
        unit_of_work=unit_of_work,
        clock=clock,
        passwords=passwords,
        tokens=tokens,
        sessions=sessions,
        authorization=authorization,
        rate_limiter=AllowAllRateLimiter(),
        policy=policy,
        password_policy=PasswordPolicy(min_length=policy.password_min_length, require_symbol=policy.password_require_symbol),
        expose_development_tokens=expose_development_tokens,
    )
    tenancy = TenancyServices(
        unit_of_work=unit_of_work,
        clock=clock,
        tokens=tokens,
        authorization=authorization,
        policy=policy,
        expose_development_tokens=expose_development_tokens,
    )
    storage = MemoryObjectStorage()
    scanner = StubScanner()
    data = DataServices(
        unit_of_work=unit_of_work,
        clock=clock,
        authorization=authorization,
        storage=storage,
        scanner=scanner,
        inspector=StubInspector(storage),
        checksums=StubChecksums(storage),
        config=ApplicationSettings(),
        storage_provider="s3",
        storage_bucket="test-bucket",
    )
    scientific = DevelopmentScientificAdapter(Environment.TEST)
    analysis = AnalysisServices(
        unit_of_work=unit_of_work,
        clock=clock,
        authorization=authorization,
        config=ApplicationSettings(),
        scientific=scientific,
    )
    analytics = StubAnalyticalReader()
    results = ResultServices(
        unit_of_work=unit_of_work,
        clock=clock,
        authorization=authorization,
        config=ApplicationSettings(),
        analytics=analytics,
        checksums=StubChecksums(storage),
        object_storage=storage,
    )
    return Harness(
        results=results,
        analytics=analytics,
        analysis=analysis,
        scientific=scientific,
        data=data,
        storage=storage,
        scanner=scanner,
        repositories=repositories,
        unit_of_work=unit_of_work,
        clock=clock,
        identity=identity,
        tenancy=tenancy,
        authorization=authorization,
        sessions=sessions,
        tokens=tokens,
        policy=policy,
        request=RequestContext(
            correlation_id="test-correlation",
            ip_hash="ip-hash",
            user_agent_summary="test-agent",
            rate_limit_key="ip-hash",
        ),
    )


__all__ = ["Harness", "NOW", "OTHER_PASSWORD", "STRONG_PASSWORD", "build_harness"]
