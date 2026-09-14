"""Shared arrangement for the Package 9 tests.

Nothing here evaluates evidence. Every payload is a *fixture-declared claim*,
exactly as an external source or a curator would have stated it, and every payload
is marked ``is_development_payload=True`` so nothing arranged here can be mistaken
for real clinical evidence. No fixture asserts a classification, and no fixture
claims a source's real content.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.application.repositories import Page
from app.application.use_cases.evidence.ingestion import (
    IngestEvidenceCommand,
    IngestEvidencePayload,
)
from app.application.use_cases.evidence.sources import (
    RegisterEvidenceSource,
    RegisterSourceCommand,
    TransitionEvidenceSource,
    TransitionSourceCommand,
)
from app.domain.value_objects.enums import (
    CriterionDirection,
    DataOrigin,
    EvidenceApplicability,
    EvidenceCategory,
    EvidenceSourceCategory,
    EvidenceStrength,
    PlatformRole,
    ScientificResourceState,
)
from app.scientific.evidence import (
    EVIDENCE_CONTRACT_VERSION,
    EvidenceClaim,
    EvidencePayload,
    EvidenceSourceIdentity,
)
from tests.support.actors import actor_for, create_account, grant_platform_role

PAGE = Page(number=1, size=25)

#: DEVELOPMENT ONLY identifiers. They name a fixture, not a real resource.
SOURCE_KEY = "fixture-evidence-source"
SOURCE_VERSION = "0.0.0-development-only"
OTHER_SOURCE_KEY = "fixture-second-evidence-source"
RELEASE = "fixture-release-1"
RETRIEVED_AT = datetime(2024, 5, 1, 12, 0, tzinfo=UTC)
RELEASED_AT = datetime(2024, 4, 1, 12, 0, tzinfo=UTC)

SUPPLIES = (
    EvidenceCategory.CLINICAL_DATABASE,
    EvidenceCategory.FUNCTIONAL,
    EvidenceCategory.POPULATION,
)


async def platform_admin(harness, email: str = "evidence-admin@example.org") -> str:
    user_id = await create_account(harness, email, display_name="Platform Admin")
    await grant_platform_role(harness, user_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    return user_id


async def registered_source(
    harness,
    admin_id: str,
    *,
    source_key: str = SOURCE_KEY,
    version: str = SOURCE_VERSION,
    category: EvidenceSourceCategory = EvidenceSourceCategory.CLINICAL_DATABASE,
    supplies: tuple[EvidenceCategory, ...] = SUPPLIES,
    supplies_strength: bool = True,
    activate: bool = True,
):
    source = await RegisterEvidenceSource(harness.evidence).execute(
        RegisterSourceCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            source_key=source_key,
            version=version,
            display_name=f"Fixture evidence source {version}",
            category=category,
            provider="fixture",
            release_label=RELEASE,
            released_at=RELEASED_AT,
            retrieved_at=RETRIEVED_AT,
            schema_version="1",
            checksum_value="0" * 64,
            supplies=supplies,
            supplies_strength=supplies_strength,
        )
    )
    if activate:
        source = await activate_source(harness, admin_id, source.id)
    return source


async def activate_source(harness, admin_id: str, source_id: str, **kwargs):
    return await TransitionEvidenceSource(harness.evidence).execute(
        TransitionSourceCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            source_id=source_id,
            state=kwargs.pop("state", ScientificResourceState.ACTIVE),
            **kwargs,
        )
    )


def claim(
    *,
    variant_id: str | None = None,
    variant_identifier: str | None = None,
    category: EvidenceCategory = EvidenceCategory.CLINICAL_DATABASE,
    direction: CriterionDirection = CriterionDirection.PATHOGENIC,
    strength: EvidenceStrength = EvidenceStrength.STRONG,
    applicability: EvidenceApplicability = EvidenceApplicability.APPLICABLE,
    evidence_key: str = "fixture-statement-1",
    source_identifier: str = "FIXTURE:1",
    summary: str | None = "fixture assertion, not a real clinical assertion",
    values: dict | None = None,
    **overrides,
) -> EvidenceClaim:
    return EvidenceClaim(
        category=category,
        variant_id=variant_id,
        variant_identifier=variant_identifier,
        direction=direction,
        strength=strength,
        applicability=applicability,
        evidence_key=evidence_key,
        source_identifier=source_identifier,
        summary=summary,
        gene_symbol=overrides.pop("gene_symbol", "FIXTUREGENE"),
        condition_identifier=overrides.pop("condition_identifier", "FIXTURE:COND"),
        values=values or {"fixture_field": "fixture_value"},
        **overrides,
    )


def evidence_payload(
    *,
    claims: tuple[EvidenceClaim, ...],
    source_key: str = SOURCE_KEY,
    version: str = SOURCE_VERSION,
    origin: DataOrigin = DataOrigin.RETRIEVED,
    retrieved_at: datetime | None = RETRIEVED_AT,
    contract_version: str = EVIDENCE_CONTRACT_VERSION,
) -> EvidencePayload:
    return EvidencePayload(
        source=EvidenceSourceIdentity(
            source_key=source_key,
            version=version,
            release_label=RELEASE,
            released_at=RELEASED_AT,
            schema_version="1",
        ),
        contract_version=contract_version,
        origin=origin,
        retrieved_at=retrieved_at,
        claims=claims,
        scientific_execution_id="sci-exec-evidence-1",
        correlation_id="corr-evidence-1",
        is_development_payload=True,
    )


async def ingest(harness, payload: EvidencePayload, **kwargs):
    return await IngestEvidencePayload(harness.evidence).execute(
        IngestEvidenceCommand(request=harness.request, payload=payload, **kwargs)
    )


__all__ = [
    "OTHER_SOURCE_KEY",
    "PAGE",
    "RELEASED_AT",
    "RETRIEVED_AT",
    "SOURCE_KEY",
    "SOURCE_VERSION",
    "SUPPLIES",
    "activate_source",
    "claim",
    "evidence_payload",
    "ingest",
    "platform_admin",
    "registered_source",
]
