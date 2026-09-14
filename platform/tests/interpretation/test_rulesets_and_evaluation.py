"""Ruleset versioning, authorization, payload validation and supersession.

The behaviour pinned down here is the part that would silently corrupt science if
it regressed: a registered ruleset version's content is immutable, an unusable
version cannot produce new suggestions, a payload must match the version it claims,
an engine cannot introduce evidence it was never given, a suggestion never becomes
a decision, and a newer suggestion supersedes rather than overwrites.
"""

from __future__ import annotations

import pytest

from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.value_objects.enums import (
    Classification,
    ClassificationDecisionRole,
    ClassificationEvaluationState,
    CriterionStrength,
    DataOrigin,
    ScientificResourceState,
)
from tests.evidence.support import claim, evidence_payload, registered_source
from tests.evidence.support import ingest as ingest_evidence
from tests.evidence.support import platform_admin as evidence_admin
from tests.interpretation.support import (
    PAGE,
    RULESET_VERSION,
    criterion_claim,
    ingest,
    interpretation_payload,
    mark_submitted,
    platform_admin,
    registered_ruleset,
    request_evaluation,
    transition_ruleset,
)
from tests.results.support import execution_for, ingest_variants, normalized_claim
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness


async def arrange():
    """An active ruleset, a variant, and one stored evidence record for it."""
    harness = build_harness()
    admin_id = await platform_admin(harness)
    ruleset = await registered_ruleset(harness, admin_id)
    source = await registered_source(harness, await evidence_admin(harness))
    _, execution, dataset_version_id = await execution_for(harness, admin_id)
    await ingest_variants(
        harness,
        admin_id,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(normalized_claim(),),
    )
    variants = await harness.repositories.variants.list_for_dataset_version(
        dataset_version_id, page=PAGE
    )
    variant = variants.items[0]
    actor = await actor_for(harness, admin_id)
    workspace_id = next(iter(actor.workspaces))
    delivery = await ingest_evidence(
        harness,
        evidence_payload(claims=(claim(variant_id=variant.id),)),
        workspace_id=workspace_id,
    )
    records = await harness.repositories.evidence_records.list_for_variant(
        variant_id=variant.id, workspace_ids=frozenset({workspace_id})
    )
    assert records, "arrangement must store the evidence the evaluation will select"
    return harness, admin_id, ruleset, variant, workspace_id, records[0], source, delivery


# --------------------------------------------------------------------------- #
# The versioned registry                                                      #
# --------------------------------------------------------------------------- #


async def test_a_ruleset_version_records_its_criteria_and_a_configuration_digest():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    ruleset = await registered_ruleset(harness, admin_id, activate=False)

    assert ruleset.state is ScientificResourceState.REGISTERED
    assert ruleset.configuration_digest
    assert set(ruleset.criteria_by_key) == {"FIXTURE_PS1", "FIXTURE_BP1"}
    assert Classification.PATHOGENIC in ruleset.declared_classifications


async def test_the_same_ruleset_key_and_version_cannot_be_registered_twice():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    await registered_ruleset(harness, admin_id)

    with pytest.raises(ConflictError):
        await registered_ruleset(harness, admin_id)


async def test_a_changed_criterion_strength_is_a_new_version_with_a_new_digest():
    """A modified strength is a different scientific configuration, not an edit."""
    from dataclasses import replace

    harness = build_harness()
    admin_id = await platform_admin(harness)
    first = await registered_ruleset(harness, admin_id)
    modified = (
        replace(first.criteria[0], default_strength=CriterionStrength.MODERATE),
        first.criteria[1],
    )
    second = await registered_ruleset(
        harness, admin_id, version="0.0.1-development-only", criteria=modified
    )

    assert second.configuration_digest != first.configuration_digest
    stored = await harness.repositories.rulesets.get(first.id)
    assert stored.criteria[0].default_strength is CriterionStrength.STRONG


async def test_only_a_platform_administrator_may_register_a_ruleset():
    harness = build_harness()
    ordinary_id = await create_account(harness, "curator@example.org")

    with pytest.raises(AuthorizationError):
        await registered_ruleset(harness, ordinary_id)


async def test_an_organization_member_cannot_activate_a_ruleset_version():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    ruleset = await registered_ruleset(harness, admin_id, activate=False)
    ordinary_id = await create_account(harness, "org-admin@example.org")

    with pytest.raises(AuthorizationError):
        await transition_ruleset(harness, ordinary_id, ruleset.id)


# --------------------------------------------------------------------------- #
# Requesting an automated evaluation                                          #
# --------------------------------------------------------------------------- #


async def test_requesting_an_evaluation_pins_the_ruleset_and_queues_one_job():
    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()

    view = await request_evaluation(
        harness,
        admin_id,
        workspace_id=workspace_id,
        variant_id=variant.id,
        ruleset_id=ruleset.id,
    )

    assert view.evaluation.state is ClassificationEvaluationState.REQUESTED
    assert view.evaluation.ruleset_version == RULESET_VERSION
    assert view.evaluation.configuration_digest == ruleset.configuration_digest
    assert view.evaluation.evidence_ids == (record.id,)
    assert view.evaluation.input_digest
    assert view.evaluation.job_id


async def test_a_retired_ruleset_version_cannot_produce_new_evaluations():
    harness, admin_id, ruleset, variant, workspace_id, *_ = await arrange()
    await transition_ruleset(
        harness, admin_id, ruleset.id, state=ScientificResourceState.DEPRECATED
    )
    await transition_ruleset(
        harness, admin_id, ruleset.id, state=ScientificResourceState.RETIRED
    )

    with pytest.raises(ConflictError):
        await request_evaluation(
            harness,
            admin_id,
            workspace_id=workspace_id,
            variant_id=variant.id,
            ruleset_id=ruleset.id,
        )


async def test_evidence_outside_the_actors_reach_is_indistinguishable_from_missing():
    harness, _admin_id, ruleset, variant, workspace_id, *_ = await arrange()
    outsider_id = await create_account(harness, "outsider@example.org")

    with pytest.raises((AuthorizationError, NotFoundError)):
        await request_evaluation(
            harness,
            outsider_id,
            workspace_id=workspace_id,
            variant_id=variant.id,
            ruleset_id=ruleset.id,
        )


async def test_an_evaluation_requires_at_least_one_evidence_record():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    ruleset = await registered_ruleset(harness, admin_id)
    _, execution, dataset_version_id = await execution_for(harness, admin_id)
    await ingest_variants(
        harness,
        admin_id,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(normalized_claim(),),
    )
    variants = await harness.repositories.variants.list_for_dataset_version(
        dataset_version_id, page=PAGE
    )
    actor = await actor_for(harness, admin_id)

    with pytest.raises(ValidationError):
        await request_evaluation(
            harness,
            admin_id,
            workspace_id=next(iter(actor.workspaces)),
            variant_id=variants.items[0].id,
            ruleset_id=ruleset.id,
        )


async def test_the_same_idempotency_key_returns_the_same_evaluation():
    harness, admin_id, ruleset, variant, workspace_id, *_ = await arrange()
    common = {
        "workspace_id": workspace_id,
        "variant_id": variant.id,
        "ruleset_id": ruleset.id,
        "idempotency_key": "fixture-key-1",
    }

    first = await request_evaluation(harness, admin_id, **common)
    second = await request_evaluation(harness, admin_id, **common)

    assert first.evaluation.id == second.evaluation.id


# --------------------------------------------------------------------------- #
# Ingesting what the engine produced                                          #
# --------------------------------------------------------------------------- #


async def ingested(harness, admin_id, ruleset, variant, workspace_id, record, **kwargs):
    view = await request_evaluation(
        harness,
        admin_id,
        workspace_id=workspace_id,
        variant_id=variant.id,
        ruleset_id=ruleset.id,
        idempotency_key=kwargs.pop("idempotency_key", None),
    )
    await mark_submitted(harness, view.evaluation)
    payload = interpretation_payload(
        evaluation_id=view.evaluation.id,
        ruleset=ruleset,
        criteria=kwargs.pop(
            "criteria", (criterion_claim(evidence_ids=(record.id,)),)
        ),
        **kwargs,
    )
    return view, await ingest(harness, payload)


async def test_a_valid_payload_is_stored_as_a_suggestion_and_never_as_a_decision():
    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()

    _, result = await ingested(
        harness, admin_id, ruleset, variant, workspace_id, record
    )

    assert result.evaluation.state is ClassificationEvaluationState.COMPLETED
    assert result.classification is not None
    assert (
        result.classification.decision_role
        is ClassificationDecisionRole.AUTOMATED_SUGGESTION
    )
    assert result.classification.is_development_payload is True
    assert result.classification.payload_digest
    assert [item.origin for item in result.criteria] == [DataOrigin.MACHINE_GENERATED]
    assert result.criteria[0].evidence_ids == (record.id,)


async def test_a_payload_naming_a_different_ruleset_version_is_rejected():
    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()

    _, result = await ingested(
        harness,
        admin_id,
        ruleset,
        variant,
        workspace_id,
        record,
        ruleset_version="9.9.9-not-what-was-requested",
    )

    assert result.evaluation.state is ClassificationEvaluationState.FAILED
    assert result.classification is None
    assert result.findings


async def test_a_criterion_strength_the_version_does_not_permit_is_rejected():
    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()

    _, result = await ingested(
        harness,
        admin_id,
        ruleset,
        variant,
        workspace_id,
        record,
        criteria=(
            criterion_claim(
                strength=CriterionStrength.SUPPORTING.value,
                evidence_ids=(record.id,),
            ),
        ),
    )

    assert "strength_not_permitted" in [item.code for item in result.findings]
    assert result.criteria == ()


async def test_an_engine_cannot_introduce_evidence_the_request_never_carried():
    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()

    _, result = await ingested(
        harness,
        admin_id,
        ruleset,
        variant,
        workspace_id,
        record,
        criteria=(criterion_claim(evidence_ids=("evd_never_authorized",)),),
    )

    assert "evidence_not_authorized" in [item.code for item in result.findings]
    assert result.criteria == ()


async def test_an_unknown_criterion_key_is_rejected_rather_than_invented():
    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()

    _, result = await ingested(
        harness,
        admin_id,
        ruleset,
        variant,
        workspace_id,
        record,
        criteria=(
            criterion_claim(criterion_key="NOT_IN_THIS_VERSION", evidence_ids=(record.id,)),
        ),
    )

    assert "criterion_unknown" in [item.code for item in result.findings]
    assert result.criteria == ()


async def test_replaying_the_same_payload_stores_nothing_further():
    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()
    view, first = await ingested(
        harness, admin_id, ruleset, variant, workspace_id, record
    )
    payload = interpretation_payload(
        evaluation_id=view.evaluation.id,
        ruleset=ruleset,
        criteria=(criterion_claim(evidence_ids=(record.id,)),),
    )

    second = await ingest(harness, payload)

    assert second.classification.id == first.classification.id
    assert len(harness.repositories.classification_evaluations.classifications) == 1


async def test_a_newer_suggestion_supersedes_without_erasing_the_earlier_one():
    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()
    _, first = await ingested(
        harness, admin_id, ruleset, variant, workspace_id, record
    )
    _, second = await ingested(
        harness,
        admin_id,
        ruleset,
        variant,
        workspace_id,
        record,
        classification=Classification.PATHOGENIC,
        combination_rule_key="fixture-rule-pathogenic",
    )

    earlier = await harness.repositories.classification_evaluations.get_classification(
        first.classification.id
    )
    assert earlier is not None
    assert earlier.superseded_by_id == second.classification.id
    assert earlier.classification is first.classification.classification
    current = await harness.repositories.classification_evaluations.current_classification(
        variant_id=variant.id, ruleset_id=ruleset.id, condition_identifier=None
    )
    assert current.id == second.classification.id
    assert second.classification.supersedes_id == first.classification.id


async def test_history_for_a_variant_stays_within_the_actors_workspaces():
    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()
    await ingested(harness, admin_id, ruleset, variant, workspace_id, record)

    visible = await harness.repositories.classification_evaluations.classification_history(
        variant_id=variant.id, workspace_ids=frozenset({workspace_id})
    )
    hidden = await harness.repositories.classification_evaluations.classification_history(
        variant_id=variant.id, workspace_ids=frozenset({"wsp_someone_else"})
    )

    assert len(visible) == 1
    assert hidden == ()
