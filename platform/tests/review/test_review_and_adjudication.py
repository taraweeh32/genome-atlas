"""Package 11: interpretation versions, human review, adjudication, finalization.

These tests assert *record-keeping* behaviour: attribution, immutability,
disagreement preservation, optimistic concurrency, authorization and tenant
isolation. No test asserts that a classification is scientifically correct.
"""

from __future__ import annotations

import pytest

from app.application.use_cases.review.interpretations import (
    InterpretationReader,
    ReclassifyInterpretation,
    ReclassifyInterpretationCommand,
)
from app.domain.errors import (
    AuthorizationError,
    ConcurrencyConflictError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.value_objects.enums import (
    Classification,
    ClassificationDecisionRole,
    InterpretationState,
    ProjectRole,
    ReviewDecision,
    ReviewState,
)
from tests.review.support import (
    ADJUDICATOR_ROLE,
    RATIONALE,
    adjudicate,
    assign,
    decide,
    finalize,
    open_interpretation,
    organization_project,
    project_member,
    record_version,
    submit,
)
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness

pytestmark = pytest.mark.asyncio


async def _owner_with_project(harness, email: str = "owner@example.org"):
    owner_id = await create_account(harness, email, display_name="Owner")
    organization, project = await organization_project(harness, owner_id)
    return owner_id, organization, project


async def test_a_variant_and_context_can_only_have_one_open_interpretation() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    await open_interpretation(harness, owner_id, project.id)
    with pytest.raises(ConflictError):
        await open_interpretation(harness, owner_id, project.id)


async def test_a_version_pins_the_decision_and_stays_readable_after_the_next_one() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    record = await open_interpretation(harness, owner_id, project.id)

    first = await record_version(
        harness,
        owner_id,
        record.id,
        classification=Classification.UNCERTAIN_SIGNIFICANCE,
        rationale="fixture first reading",
    )
    second = await record_version(
        harness,
        owner_id,
        record.id,
        classification=Classification.LIKELY_PATHOGENIC,
        rationale="fixture second reading",
    )

    assert (first.version_number, second.version_number) == (1, 2)
    detail = await InterpretationReader(harness.review).detail(
        actor=await actor_for(harness, owner_id),
        request=harness.request,
        interpretation_id=record.id,
    )
    # The earlier reading is not rewritten by the later one.
    stored = {version.id: version for version in detail.versions}
    assert stored[first.id].classification is Classification.UNCERTAIN_SIGNIFICANCE
    assert stored[first.id].rationale == "fixture first reading"
    assert detail.current_version.id == second.id


async def test_a_version_requires_recorded_reasoning() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    record = await open_interpretation(harness, owner_id, project.id)
    with pytest.raises(ValidationError):
        await record_version(harness, owner_id, record.id, rationale="   ")


async def test_authoring_cannot_claim_an_adjudicated_or_final_role() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    record = await open_interpretation(harness, owner_id, project.id)
    for role in (
        ClassificationDecisionRole.ADJUDICATED_DECISION,
        ClassificationDecisionRole.FINAL_INTERPRETATION,
    ):
        with pytest.raises(ValidationError):
            await record_version(harness, owner_id, record.id, decision_role=role)


async def test_a_reviewer_decision_is_attributed_and_never_replaced() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id)
    await assign(harness, owner_id, record.id, reviewer_id)

    first = await decide(
        harness,
        reviewer_id,
        record.id,
        version.id,
        decision=ReviewDecision.OVERRIDE,
        proposed_classification=Classification.LIKELY_PATHOGENIC,
        rationale="fixture reviewer reasoning",
    )
    second = await decide(
        harness,
        reviewer_id,
        record.id,
        version.id,
        decision=ReviewDecision.ACCEPT,
        rationale="fixture reviewer reasoning, revised",
    )

    detail = await InterpretationReader(harness.review).detail(
        actor=await actor_for(harness, owner_id),
        request=harness.request,
        interpretation_id=record.id,
    )
    ids = {decision.id for decision in detail.decisions}
    # Append-only: the revised decision does not erase the original one.
    assert {first.id, second.id} <= ids
    assert all(decision.reviewer_user_id == reviewer_id for decision in detail.decisions)


async def test_a_stale_reviewer_cannot_decide_against_an_outdated_version() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id)
    await assign(harness, owner_id, record.id, reviewer_id)
    await record_version(harness, owner_id, record.id, rationale="fixture newer reading")

    with pytest.raises(ConflictError):
        await decide(
            harness,
            reviewer_id,
            record.id,
            version.id,
            decision=ReviewDecision.ACCEPT,
            expected_current_version_number=1,
        )


async def test_reviewer_disagreement_escalates_and_keeps_both_positions() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    first_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer-one@example.org", ProjectRole.REVIEWER
    )
    second_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer-two@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id)
    await assign(harness, owner_id, record.id, first_id)
    await assign(harness, owner_id, record.id, second_id)

    await decide(
        harness,
        first_id,
        record.id,
        version.id,
        decision=ReviewDecision.OVERRIDE,
        proposed_classification=Classification.LIKELY_PATHOGENIC,
        rationale="fixture reviewer reasoning",
    )
    await submit(harness, first_id, record.id)
    await decide(
        harness,
        second_id,
        record.id,
        version.id,
        decision=ReviewDecision.OVERRIDE,
        proposed_classification=Classification.LIKELY_BENIGN,
        rationale="fixture reviewer reasoning",
    )
    await submit(harness, second_id, record.id)

    detail = await InterpretationReader(harness.review).detail(
        actor=await actor_for(harness, owner_id),
        request=harness.request,
        interpretation_id=record.id,
    )
    assert detail.interpretation.state is InterpretationState.ADJUDICATION
    proposals = {
        decision.reviewer_user_id: decision.proposed_classification
        for decision in detail.decisions
        if decision.proposed_classification is not None
    }
    assert proposals[first_id] is Classification.LIKELY_PATHOGENIC
    assert proposals[second_id] is Classification.LIKELY_BENIGN


async def test_agreeing_reviewers_approve_without_adjudication() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id)
    await assign(harness, owner_id, record.id, reviewer_id)
    await decide(harness, reviewer_id, record.id, version.id, decision=ReviewDecision.ACCEPT)
    await submit(harness, reviewer_id, record.id)
    detail = await InterpretationReader(harness.review).detail(
        actor=await actor_for(harness, owner_id),
        request=harness.request,
        interpretation_id=record.id,
    )
    assert detail.interpretation.state is InterpretationState.APPROVED


async def test_adjudication_records_its_own_decision_role_and_approves() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    first_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer-one@example.org", ProjectRole.REVIEWER
    )
    second_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer-two@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id)
    proposals = (
        (first_id, Classification.LIKELY_PATHOGENIC),
        (second_id, Classification.LIKELY_BENIGN),
    )
    for reviewer_id, _ in proposals:
        await assign(harness, owner_id, record.id, reviewer_id)
    for reviewer_id, proposal in proposals:
        await decide(
            harness,
            reviewer_id,
            record.id,
            version.id,
            decision=ReviewDecision.OVERRIDE,
            proposed_classification=proposal,
            rationale="fixture reviewer reasoning",
        )
        await submit(harness, reviewer_id, record.id)

    adjudicated = await adjudicate(
        harness,
        owner_id,
        record.id,
        classification=Classification.UNCERTAIN_SIGNIFICANCE,
    )
    assert adjudicated.decision_role is ClassificationDecisionRole.ADJUDICATED_DECISION

    detail = await InterpretationReader(harness.review).detail(
        actor=await actor_for(harness, owner_id),
        request=harness.request,
        interpretation_id=record.id,
    )
    assert detail.interpretation.state is InterpretationState.APPROVED
    # The reviewer positions the adjudication resolved are still on the record.
    kept = {
        d.reviewer_user_id: d.proposed_classification
        for d in detail.decisions
        if not d.is_adjudication
    }
    assert kept[first_id] is Classification.LIKELY_PATHOGENIC
    assert kept[second_id] is Classification.LIKELY_BENIGN


async def test_a_reviewer_cannot_adjudicate_their_own_disagreement() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id)
    await assign(harness, owner_id, record.id, reviewer_id)
    await decide(harness, reviewer_id, record.id, version.id, decision=ReviewDecision.ACCEPT)
    await submit(harness, reviewer_id, record.id)
    # Reviewing does not imply adjudicating, even inside the same project.
    with pytest.raises((AuthorizationError, NotFoundError, ConflictError)):
        await adjudicate(harness, reviewer_id, record.id)


async def test_finalization_requires_approval_and_then_freezes_the_version() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id)

    with pytest.raises(ConflictError):
        await finalize(harness, owner_id, record.id)

    await assign(harness, owner_id, record.id, reviewer_id)
    await decide(harness, reviewer_id, record.id, version.id, decision=ReviewDecision.ACCEPT)
    await submit(harness, reviewer_id, record.id)

    finalized = await finalize(harness, owner_id, record.id)
    assert finalized.finalized_at is not None
    assert finalized.finalized_by == owner_id

    # A finalized interpretation is closed: no new version, no second finalization.
    with pytest.raises(ConflictError):
        await record_version(harness, owner_id, record.id)
    with pytest.raises(ConflictError):
        await finalize(harness, owner_id, record.id)


async def test_finalization_refuses_a_stale_expected_version() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id)
    await assign(harness, owner_id, record.id, reviewer_id)
    await decide(harness, reviewer_id, record.id, version.id, decision=ReviewDecision.ACCEPT)
    await submit(harness, reviewer_id, record.id)
    with pytest.raises((ConflictError, ConcurrencyConflictError)):
        await finalize(harness, owner_id, record.id, expected_version_number=99)


async def test_reclassification_supersedes_without_rewriting_history() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(
        harness, owner_id, record.id, classification=Classification.UNCERTAIN_SIGNIFICANCE
    )
    await assign(harness, owner_id, record.id, reviewer_id)
    await decide(harness, reviewer_id, record.id, version.id, decision=ReviewDecision.ACCEPT)
    await submit(harness, reviewer_id, record.id)
    finalized = await finalize(harness, owner_id, record.id)

    successor = await ReclassifyInterpretation(harness.review).execute(
        ReclassifyInterpretationCommand(
            actor=await actor_for(harness, owner_id),
            request=harness.request,
            interpretation_id=record.id,
            reason="fixture reclassification reason",
        )
    )
    assert successor.id != record.id

    detail = await InterpretationReader(harness.review).detail(
        actor=await actor_for(harness, owner_id),
        request=harness.request,
        interpretation_id=record.id,
    )
    assert detail.interpretation.state is InterpretationState.SUPERSEDED
    kept = {version.id: version for version in detail.versions}[finalized.id]
    assert kept.classification is Classification.UNCERTAIN_SIGNIFICANCE
    assert kept.finalized_at is not None


async def test_an_outsider_cannot_see_or_touch_another_tenants_interpretation() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    record = await open_interpretation(harness, owner_id, project.id)
    outsider_id = await create_account(harness, "outsider@example.org")

    # Missing and unauthorized look identical: existence must not be probeable.
    with pytest.raises(NotFoundError):
        await InterpretationReader(harness.review).detail(
            actor=await actor_for(harness, outsider_id),
            request=harness.request,
            interpretation_id=record.id,
        )
    with pytest.raises(NotFoundError):
        await record_version(harness, outsider_id, record.id)
    with pytest.raises(NotFoundError):
        await finalize(harness, outsider_id, record.id)


async def test_a_project_viewer_cannot_author_or_finalize() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    viewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "viewer@example.org", ProjectRole.VIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    detail = await InterpretationReader(harness.review).detail(
        actor=await actor_for(harness, viewer_id),
        request=harness.request,
        interpretation_id=record.id,
    )
    assert detail.interpretation.id == record.id
    with pytest.raises((AuthorizationError, NotFoundError)):
        await record_version(harness, viewer_id, record.id)


async def test_an_unassigned_member_cannot_record_a_review_decision() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id)
    with pytest.raises((ConflictError, AuthorizationError, NotFoundError)):
        await decide(
            harness, reviewer_id, record.id, version.id, decision=ReviewDecision.ACCEPT
        )


async def test_assignment_moves_the_interpretation_into_review() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    await record_version(harness, owner_id, record.id)
    assignment = await assign(harness, owner_id, record.id, reviewer_id)
    assert assignment.state in {ReviewState.ASSIGNED, ReviewState.IN_PROGRESS}

    detail = await InterpretationReader(harness.review).detail(
        actor=await actor_for(harness, owner_id),
        request=harness.request,
        interpretation_id=record.id,
    )
    assert detail.interpretation.state is InterpretationState.IN_REVIEW
    assert [a.reviewer_user_id for a in detail.assignments] == [reviewer_id]


async def test_an_adjudicator_assignment_is_recorded_in_its_own_role() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    adjudicator_id = await project_member(
        harness, owner_id, organization.id, project.id, "adjudicator@example.org", ProjectRole.MANAGER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    await record_version(harness, owner_id, record.id)
    assignment = await assign(
        harness, owner_id, record.id, adjudicator_id, review_role=ADJUDICATOR_ROLE
    )
    assert assignment.review_role == ADJUDICATOR_ROLE


async def test_a_version_cannot_pin_evidence_from_a_different_variant() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    record = await open_interpretation(harness, owner_id, project.id)
    with pytest.raises((ValidationError, NotFoundError)):
        await record_version(
            harness,
            owner_id,
            record.id,
            evidence_item_ids=("evi_does_not_exist",),
        )


async def test_the_review_workspace_reads_everything_in_one_authorized_call() -> None:
    harness = build_harness()
    owner_id, organization, project = await _owner_with_project(harness)
    reviewer_id = await project_member(
        harness, owner_id, organization.id, project.id, "reviewer@example.org", ProjectRole.REVIEWER
    )
    record = await open_interpretation(harness, owner_id, project.id)
    version = await record_version(harness, owner_id, record.id, rationale=RATIONALE)
    await assign(harness, owner_id, record.id, reviewer_id)
    await decide(harness, reviewer_id, record.id, version.id, decision=ReviewDecision.ACCEPT)

    detail = await InterpretationReader(harness.review).detail(
        actor=await actor_for(harness, owner_id),
        request=harness.request,
        interpretation_id=record.id,
    )
    assert detail.versions and detail.assignments and detail.decisions
    assert detail.current_version.rationale == RATIONALE
