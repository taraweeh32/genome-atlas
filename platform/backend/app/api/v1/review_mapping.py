"""Mapping between the review layer and its transport schemas.

Explicit and one-directional, like the other mapping modules. The judgement encoded
here: a version response always carries both the automated suggestion and the recorded
decision, and always carries the disagreement summary — a client must be able to see
that reviewers disagreed even after the disagreement was resolved.
"""

from __future__ import annotations

from app.api.v1.schemas.review import (
    InterpretationDetailResponse,
    InterpretationResponse,
    InterpretationVersionResponse,
    ReviewAssignmentResponse,
    ReviewDecisionResponse,
)
from app.application.use_cases.review.interpretations import InterpretationDetail
from app.domain.review.entities import (
    InterpretationRecord,
    InterpretationVersionRecord,
    ReviewAssignmentRecord,
    ReviewDecisionRecord,
)


def interpretation_response(record: InterpretationRecord) -> InterpretationResponse:
    return InterpretationResponse(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        variant_id=record.variant_id,
        sample_id=record.sample_id,
        condition_identifier=record.condition_identifier,
        condition_term=record.condition_term,
        state=record.state.value,
        review_state=record.review_state.value,
        current_version_id=record.current_version_id,
        current_version_number=record.current_version_number,
        version=record.version,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def version_response(
    record: InterpretationVersionRecord,
) -> InterpretationVersionResponse:
    return InterpretationVersionResponse(
        id=record.id,
        interpretation_id=record.interpretation_id,
        version_number=record.version_number,
        classification=record.classification.value,
        suggested_classification=(
            record.suggested_classification.value
            if record.suggested_classification
            else None
        ),
        decision_role=record.decision_role.value,
        origin=record.origin.value,
        rationale=record.rationale,
        clinical_significance_statement=record.clinical_significance_statement,
        ruleset_id=record.ruleset_id,
        ruleset_version=record.ruleset_version,
        classification_evaluation_id=record.classification_evaluation_id,
        automated_classification_id=record.automated_classification_id,
        criterion_evaluation_ids=list(record.criterion_evaluation_ids),
        evidence_item_ids=list(record.evidence_item_ids),
        disagreement_summary=dict(record.disagreement_summary),
        review_round=record.review_round,
        authored_by=record.authored_by,
        adjudicated_by=record.adjudicated_by,
        adjudicated_at=record.adjudicated_at,
        finalized_by=record.finalized_by,
        finalized_at=record.finalized_at,
        supersedes_version_id=record.supersedes_version_id,
        created_at=record.created_at,
    )


def assignment_response(record: ReviewAssignmentRecord) -> ReviewAssignmentResponse:
    return ReviewAssignmentResponse(
        id=record.id,
        interpretation_id=record.interpretation_id,
        reviewer_user_id=record.reviewer_user_id,
        review_role=record.review_role,
        state=record.state.value,
        review_round=record.review_round,
        assigned_by=record.assigned_by,
        assigned_at=record.assigned_at,
        due_at=record.due_at,
        completed_at=record.completed_at,
    )


def decision_response(record: ReviewDecisionRecord) -> ReviewDecisionResponse:
    return ReviewDecisionResponse(
        id=record.id,
        interpretation_id=record.interpretation_id,
        interpretation_version_id=record.interpretation_version_id,
        reviewer_user_id=record.reviewer_user_id,
        decision=record.decision.value,
        decision_role=record.decision_role.value,
        criterion_evaluation_id=record.criterion_evaluation_id,
        proposed_classification=(
            record.proposed_classification.value
            if record.proposed_classification
            else None
        ),
        previous_classification=(
            record.previous_classification.value
            if record.previous_classification
            else None
        ),
        rationale=record.rationale,
        review_round=record.review_round,
        is_adjudication=record.is_adjudication,
        resolves_decision_id=record.resolves_decision_id,
        decided_at=record.decided_at,
    )


def detail_response(detail: InterpretationDetail) -> InterpretationDetailResponse:
    current = detail.current_version
    return InterpretationDetailResponse(
        interpretation=interpretation_response(detail.interpretation),
        current_version=version_response(current) if current else None,
        versions=[version_response(item) for item in detail.versions],
        assignments=[assignment_response(item) for item in detail.assignments],
        decisions=[decision_response(item) for item in detail.decisions],
    )


__all__ = [
    "assignment_response",
    "decision_response",
    "detail_response",
    "interpretation_response",
    "version_response",
]
