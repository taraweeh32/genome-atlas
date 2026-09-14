"""Shared arrangement for the Package 10 tests.

Nothing here evaluates a criterion or decides a classification. Every ruleset is a
*fixture-declared guideline stand-in* and every payload is a fixture-declared claim
carried as though an external rules engine had produced it, marked
``is_development_payload=True`` so it can never be mistaken for a scientific
result. No fixture asserts that a real ACMG criterion is met by a real variant.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.application.repositories import Page
from app.application.use_cases.interpretation.evaluations import (
    RequestClassificationEvaluation,
    RequestEvaluationCommand,
)
from app.application.use_cases.interpretation.ingestion import (
    IngestInterpretationCommand,
    IngestInterpretationPayload,
)
from app.application.use_cases.interpretation.rulesets import (
    RegisterRuleset,
    RegisterRulesetCommand,
    TransitionRuleset,
    TransitionRulesetCommand,
)
from app.domain.interpretation.entities import CombinationRule, CriterionDefinition
from app.domain.value_objects.enums import (
    Classification,
    ClassificationEvaluationState,
    CriterionDirection,
    CriterionFamily,
    CriterionStrength,
    PlatformRole,
    RulesetSpecificationScope,
    ScientificResourceState,
)
from app.scientific.interpretation import (
    INTERPRETATION_CONTRACT_VERSION,
    ClassificationClaim,
    CriterionEvaluationClaim,
    InterpretationPayload,
    RulesetIdentity,
)
from tests.support.actors import actor_for, create_account, grant_platform_role

PAGE = Page(number=1, size=25)

#: DEVELOPMENT ONLY identifiers. They name a fixture, not a published guideline.
RULESET_KEY = "fixture-ruleset"
RULESET_VERSION = "0.0.0-development-only"
PRODUCED_AT = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

#: Two criteria in opposite directions plus one that a specification is allowed to
#: apply at a modified strength. Their keys deliberately look like the framework's
#: families because that vocabulary is what a ruleset version records.
CRITERIA = (
    CriterionDefinition(
        criterion_key="FIXTURE_PS1",
        family=CriterionFamily.PS,
        direction=CriterionDirection.PATHOGENIC,
        default_strength=CriterionStrength.STRONG,
        permitted_strengths=(CriterionStrength.STRONG, CriterionStrength.MODERATE),
        requires_evidence=True,
    ),
    CriterionDefinition(
        criterion_key="FIXTURE_BP1",
        family=CriterionFamily.BP,
        direction=CriterionDirection.BENIGN,
        default_strength=CriterionStrength.SUPPORTING,
        permitted_strengths=(CriterionStrength.SUPPORTING,),
        requires_evidence=True,
    ),
)

COMBINATION_RULES = (
    CombinationRule(
        rule_key="fixture-rule-pathogenic",
        classification=Classification.PATHOGENIC,
        requirements={"note": "fixture combination rule, not a guideline rule"},
        precedence=1,
    ),
    CombinationRule(
        rule_key="fixture-rule-uncertain",
        classification=Classification.UNCERTAIN_SIGNIFICANCE,
        requirements={"note": "fixture combination rule, not a guideline rule"},
        precedence=2,
    ),
)


async def platform_admin(harness, email: str = "ruleset-admin@example.org") -> str:
    user_id = await create_account(harness, email, display_name="Platform Admin")
    await grant_platform_role(harness, user_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    return user_id


async def registered_ruleset(
    harness,
    admin_id: str,
    *,
    ruleset_key: str = RULESET_KEY,
    version: str = RULESET_VERSION,
    criteria: tuple[CriterionDefinition, ...] = CRITERIA,
    combination_rules: tuple[CombinationRule, ...] = COMBINATION_RULES,
    specification_scope: RulesetSpecificationScope = RulesetSpecificationScope.GENERAL,
    gene_symbol: str | None = None,
    activate: bool = True,
    **overrides,
):
    ruleset = await RegisterRuleset(harness.interpretation).execute(
        RegisterRulesetCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            ruleset_key=ruleset_key,
            version=version,
            display_name=f"Fixture ruleset {version}",
            guideline_source="fixture guideline source (development only)",
            criteria=criteria,
            combination_rules=combination_rules,
            specification_scope=specification_scope,
            gene_symbol=gene_symbol,
            **overrides,
        )
    )
    if activate:
        ruleset = await transition_ruleset(harness, admin_id, ruleset.id)
    return ruleset


async def transition_ruleset(
    harness,
    admin_id: str,
    ruleset_id: str,
    state: ScientificResourceState = ScientificResourceState.ACTIVE,
    **kwargs,
):
    return await TransitionRuleset(harness.interpretation).execute(
        TransitionRulesetCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            ruleset_id=ruleset_id,
            state=state,
            **kwargs,
        )
    )


async def request_evaluation(harness, actor_id: str, **kwargs):
    return await RequestClassificationEvaluation(harness.interpretation).execute(
        RequestEvaluationCommand(
            actor=await actor_for(harness, actor_id),
            request=harness.request,
            **kwargs,
        )
    )


def criterion_claim(
    *,
    criterion_key: str = "FIXTURE_PS1",
    applied: bool = True,
    strength: str = CriterionStrength.STRONG.value,
    direction: str | None = CriterionDirection.PATHOGENIC.value,
    evidence_ids: tuple[str, ...] = (),
    rationale: str | None = "fixture rationale, not a scientific rationale",
    **overrides,
) -> CriterionEvaluationClaim:
    return CriterionEvaluationClaim(
        criterion_key=criterion_key,
        applied=applied,
        strength=strength,
        direction=direction,
        evidence_ids=evidence_ids,
        rationale=rationale,
        method="fixture-engine",
        **overrides,
    )


def interpretation_payload(
    *,
    evaluation_id: str,
    ruleset,
    criteria: tuple[CriterionEvaluationClaim, ...],
    classification: Classification | None = Classification.UNCERTAIN_SIGNIFICANCE,
    combination_rule_key: str | None = "fixture-rule-uncertain",
    contract_version: str = INTERPRETATION_CONTRACT_VERSION,
    ruleset_key: str | None = None,
    ruleset_version: str | None = None,
    configuration_digest: str | None = None,
    applied_criterion_keys: tuple[str, ...] | None = None,
) -> InterpretationPayload:
    claim = (
        ClassificationClaim(
            classification=classification.value,
            combination_rule_key=combination_rule_key,
            rationale="fixture suggestion, not a clinical decision",
            applied_criterion_keys=applied_criterion_keys
            if applied_criterion_keys is not None
            else tuple(item.criterion_key for item in criteria if item.applied),
            computation={"note": "fixture working, stored verbatim"},
        )
        if classification is not None
        else None
    )
    return InterpretationPayload(
        contract_version=contract_version,
        evaluation_id=evaluation_id,
        ruleset=RulesetIdentity(
            ruleset_key=ruleset_key or ruleset.ruleset_key,
            ruleset_version=ruleset_version or ruleset.version,
            ruleset_id=ruleset.id,
            guideline_source=ruleset.guideline_source,
            configuration_digest=configuration_digest
            if configuration_digest is not None
            else ruleset.configuration_digest,
        ),
        criteria=criteria,
        classification=claim,
        engine_resource_id="fixture-engine-resource",
        engine_version="0.0.0-development-only",
        environment_version="fixture-environment",
        node_identity="fixture-node",
        scientific_execution_id="sci-exec-interpretation-1",
        produced_at=PRODUCED_AT,
        is_development_payload=True,
    )


async def mark_submitted(harness, evaluation):
    """Advance a requested evaluation as the worker's submission would.

    The tests here exercise validation and storage of what an engine returned; the
    gateway submission itself is covered by the worker/boundary test.
    """
    return await harness.repositories.classification_evaluations.save(
        evaluation.transition_to(
            ClassificationEvaluationState.SUBMITTED, at=harness.clock.now()
        )
    )


async def ingest(harness, payload: InterpretationPayload, **kwargs):
    return await IngestInterpretationPayload(harness.interpretation).execute(
        IngestInterpretationCommand(request=harness.request, payload=payload, **kwargs)
    )


__all__ = [
    "COMBINATION_RULES",
    "CRITERIA",
    "PAGE",
    "PRODUCED_AT",
    "RULESET_KEY",
    "RULESET_VERSION",
    "criterion_claim",
    "ingest",
    "interpretation_payload",
    "mark_submitted",
    "platform_admin",
    "registered_ruleset",
    "request_evaluation",
    "transition_ruleset",
]
