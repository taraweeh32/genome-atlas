"""Domain records for interpretations, their versions and human review.

Versioning rule, stated once: a finalized interpretation version is immutable. A
correction or a reclassification is a *new* version that names the version it
supersedes and the reason. Nothing rewrites history, so a report that cited version
3 still means what it meant when it was written.

Attribution rule, stated once: every recorded action names the person or the engine
that produced it. ``decision_role`` distinguishes an automated suggestion from a
reviewer decision, an adjudicated decision and a final interpretation, and no code
path collapses two of them into one row.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.domain.errors import ConflictError, ValidationError
from app.domain.value_objects.enums import (
    Classification,
    ClassificationDecisionRole,
    DataOrigin,
    InterpretationState,
    ReviewDecision,
    ReviewState,
)


@dataclass(frozen=True, slots=True)
class InterpretationRecord:
    """The interpretation definition: a decision context for one variant.

    The definition is mutable in the narrow sense that its lifecycle state and its
    pointer to the current version move forward. The scientific content lives in the
    versions, which are never rewritten.
    """

    id: str
    workspace_id: str
    project_id: str
    variant_id: str
    created_by: str
    state: InterpretationState = InterpretationState.DRAFT
    review_state: ReviewState = ReviewState.NOT_STARTED
    sample_id: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None
    current_version_id: str | None = None
    current_version_number: int = 0
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def with_state(
        self,
        state: InterpretationState,
        *,
        review_state: ReviewState | None = None,
    ) -> InterpretationRecord:
        return replace(
            self,
            state=state,
            review_state=self.review_state if review_state is None else review_state,
        )

    def with_current_version(
        self, *, version_id: str, version_number: int
    ) -> InterpretationRecord:
        return replace(
            self, current_version_id=version_id, current_version_number=version_number
        )

    @property
    def is_finalized(self) -> bool:
        return self.state is InterpretationState.FINALIZED


@dataclass(frozen=True, slots=True)
class InterpretationVersionRecord:
    """One immutable version of an interpretation.

    A version pins everything the decision rested on: the ruleset version, the
    automated evaluation and suggestion it started from, the exact criterion
    evaluations, the exact evidence item versions, and the disagreement that stood
    at the time. Those pins are what make the decision reproducible later, when the
    resources behind them have moved on.
    """

    id: str
    interpretation_id: str
    version_number: int
    classification: Classification
    origin: DataOrigin
    decision_role: ClassificationDecisionRole
    suggested_classification: Classification | None = None
    rationale: str | None = None
    clinical_significance_statement: str | None = None
    ruleset_id: str | None = None
    ruleset_version: str | None = None
    classification_evaluation_id: str | None = None
    automated_classification_id: str | None = None
    analysis_execution_id: str | None = None
    scientific_execution_id: str | None = None
    #: The exact criterion evaluations and evidence item versions pinned in.
    criterion_evaluation_ids: tuple[str, ...] = ()
    evidence_item_ids: tuple[str, ...] = ()
    evaluation_snapshot: dict[str, Any] = field(default_factory=dict)
    conflict_summary: dict[str, Any] = field(default_factory=dict)
    disagreement_summary: dict[str, Any] = field(default_factory=dict)
    review_round: int = 1
    authored_by: str | None = None
    adjudicated_by: str | None = None
    adjudicated_at: datetime | None = None
    finalized_by: str | None = None
    finalized_at: datetime | None = None
    supersedes_version_id: str | None = None
    reclassification_reason: str | None = None
    created_at: datetime | None = None

    @property
    def is_final(self) -> bool:
        return self.decision_role is ClassificationDecisionRole.FINAL_INTERPRETATION

    def finalized(self, *, by: str, at: datetime) -> InterpretationVersionRecord:
        """Turn this version into the final interpretation.

        Refuses on an already-finalized version: finalizing twice would mean the
        immutable record had been reopened.
        """
        if self.finalized_at is not None:
            raise ConflictError(
                "this interpretation version is already finalized; "
                "record a new version instead",
                details={"interpretation_version_id": self.id},
            )
        return replace(
            self,
            decision_role=ClassificationDecisionRole.FINAL_INTERPRETATION,
            finalized_by=by,
            finalized_at=at,
        )


@dataclass(frozen=True, slots=True)
class ReviewAssignmentRecord:
    """One reviewer or adjudicator assigned to one interpretation, per round."""

    id: str
    interpretation_id: str
    workspace_id: str
    project_id: str
    reviewer_user_id: str
    review_role: str = "reviewer"
    state: ReviewState = ReviewState.ASSIGNED
    review_round: int = 1
    assigned_by: str | None = None
    assigned_at: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    version: int = 1

    def with_state(
        self, state: ReviewState, *, completed_at: datetime | None = None
    ) -> ReviewAssignmentRecord:
        return replace(self, state=state, completed_at=completed_at or self.completed_at)


@dataclass(frozen=True, slots=True)
class ReviewDecisionRecord:
    """One append-only reviewer or adjudicator action.

    A decision row is never updated and never deleted. An adjudication names the
    decisions it resolved through ``resolves_decision_id``; the resolved decision
    keeps its own row exactly as its author left it, which is how the history of a
    disagreement survives its resolution.
    """

    id: str
    interpretation_id: str
    interpretation_version_id: str
    reviewer_user_id: str
    decision: ReviewDecision
    decided_at: datetime
    decision_role: ClassificationDecisionRole = (
        ClassificationDecisionRole.REVIEWER_DECISION
    )
    review_assignment_id: str | None = None
    criterion_evaluation_id: str | None = None
    proposed_classification: Classification | None = None
    previous_classification: Classification | None = None
    rationale: str | None = None
    review_round: int = 1
    is_adjudication: bool = False
    resolves_decision_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.is_adjudication and (
            self.decision_role is not ClassificationDecisionRole.ADJUDICATED_DECISION
        ):
            raise ValidationError(
                "an adjudication must be recorded as an adjudicated decision",
                details={"decision_role": self.decision_role.value},
            )
        if self.decision in _CRITERION_DECISIONS and self.criterion_evaluation_id is None:
            raise ValidationError(
                "a criterion-level decision must name the criterion evaluation it acts on",
                details={"decision": self.decision.value},
            )
        if self.decision is ReviewDecision.OVERRIDE and not self.rationale:
            raise ValidationError(
                "an override must carry a rationale",
                details={"decision": self.decision.value},
            )


#: Decisions that act on one criterion rather than on the whole interpretation.
_CRITERION_DECISIONS: frozenset[ReviewDecision] = frozenset(
    {
        ReviewDecision.ADD_CRITERION,
        ReviewDecision.REMOVE_CRITERION,
        ReviewDecision.MODIFY,
    }
)


__all__ = [
    "InterpretationRecord",
    "InterpretationVersionRecord",
    "ReviewAssignmentRecord",
    "ReviewDecisionRecord",
]
