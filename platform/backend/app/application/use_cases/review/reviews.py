"""Reviewer assignment and the append-only record of reviewer decisions.

Three separable things happen here, and they stay separable:

* a reviewer is **assigned** to a round of review on an interpretation;
* a reviewer **records a decision** — accept, reject, modify, add or remove a
  criterion, override, abstain — against a specific interpretation version. Decisions
  are appended, never edited, so a later adjudication cannot quietly rewrite what a
  reviewer originally said;
* a reviewer **submits** their review, closing their own assignment. When submission
  completes the round and the submitted proposals disagree, the interpretation moves
  to adjudication rather than silently picking one of them.

No criterion is evaluated here. A reviewer's "modify" is recorded as *that reviewer's
proposal about a criterion*, next to the automated evaluation, which is left intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.review.dependencies import (
    INTERPRETATION_ADJUDICATE,
    INTERPRETATION_REVIEW,
    ReviewServices,
    load_authorized_interpretation,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.review.entities import (
    InterpretationRecord,
    ReviewAssignmentRecord,
    ReviewDecisionRecord,
)
from app.domain.review.workflow import (
    check_interpretation_transition,
    check_review_transition,
    disagreement_between,
    require_not_finalized,
)
from app.domain.value_objects.enums import (
    AuditOutcome,
    Classification,
    ClassificationDecisionRole,
    InterpretationState,
    ReviewDecision,
    ReviewState,
)
from app.infrastructure.persistence.repositories.base import new_id

#: Assignment roles this package understands. An adjudicator is assigned the same
#: way a reviewer is, but adjudicating still requires the adjudication permission.
REVIEWER_ROLE = "reviewer"
ADJUDICATOR_ROLE = "adjudicator"


@dataclass(frozen=True, slots=True)
class AssignReviewerCommand:
    actor: ActorContext
    request: RequestContext
    interpretation_id: str
    reviewer_user_id: str
    review_role: str = REVIEWER_ROLE
    due_at: Any = None


@dataclass(frozen=True, slots=True)
class RecordReviewDecisionCommand:
    actor: ActorContext
    request: RequestContext
    interpretation_id: str
    interpretation_version_id: str
    decision: ReviewDecision
    rationale: str | None = None
    criterion_evaluation_id: str | None = None
    proposed_classification: Classification | None = None
    details: dict[str, Any] | None = None
    #: Optimistic concurrency: the version the reviewer was looking at. A stale
    #: value means somebody appended a newer version meanwhile.
    expected_current_version_number: int | None = None


@dataclass(frozen=True, slots=True)
class SubmitReviewCommand:
    actor: ActorContext
    request: RequestContext
    interpretation_id: str


class AssignReviewer:
    """Assign a reviewer or adjudicator to the interpretation's current round."""

    def __init__(self, services: ReviewServices) -> None:
        self._services = services

    async def execute(self, command: AssignReviewerCommand) -> ReviewAssignmentRecord:
        now = self._services.clock.now()
        if command.review_role not in {REVIEWER_ROLE, ADJUDICATOR_ROLE}:
            raise ValidationError(
                "unknown review role", details={"review_role": command.review_role}
            )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            record, _ = await load_authorized_interpretation(
                self._services,
                repositories,
                command.actor,
                interpretation_id=command.interpretation_id,
                action=INTERPRETATION_ADJUDICATE,
                recorder=recorder,
                occurred_at=now,
            )
            require_not_finalized(record.state, interpretation_id=record.id)
            review_round = _current_round(record)
            existing = await repositories.reviews.find_assignment(
                interpretation_id=record.id,
                reviewer_user_id=command.reviewer_user_id,
                review_round=review_round,
            )
            if existing is not None:
                raise ConflictError(
                    "this reviewer is already assigned to the current review round",
                    details={"review_assignment_id": existing.id},
                )
            assignment = ReviewAssignmentRecord(
                id=new_id("rasn"),
                interpretation_id=record.id,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                reviewer_user_id=command.reviewer_user_id,
                review_role=command.review_role,
                review_round=review_round,
                assigned_by=command.actor.actor_id,
                assigned_at=now,
                due_at=command.due_at,
            )
            stored = await repositories.reviews.add_assignment(assignment)

            if record.state in {InterpretationState.DRAFT, InterpretationState.AUTOMATED}:
                check_interpretation_transition(record.state, InterpretationState.IN_REVIEW)
                await repositories.interpretations.save(
                    record.with_state(
                        InterpretationState.IN_REVIEW, review_state=ReviewState.ASSIGNED
                    )
                )
            elif record.review_state is ReviewState.NOT_STARTED:
                await repositories.interpretations.save(
                    record.with_state(record.state, review_state=ReviewState.ASSIGNED)
                )

            await recorder.audit(
                action="review.assigned",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="review_assignment",
                resource_id=stored.id,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                detail={
                    "interpretation_id": record.id,
                    "reviewer_user_id": stored.reviewer_user_id,
                    "review_role": stored.review_role,
                    "review_round": stored.review_round,
                },
            )
            await recorder.event(
                event_type=EventType.REVIEW_ASSIGNED,
                aggregate_type="interpretation",
                aggregate_id=record.id,
                occurred_at=now,
                payload={
                    "review_assignment_id": stored.id,
                    "reviewer_user_id": stored.reviewer_user_id,
                    "review_role": stored.review_role,
                },
            )
            return stored


class RecordReviewDecision:
    """Append one reviewer action against one interpretation version."""

    def __init__(self, services: ReviewServices) -> None:
        self._services = services

    async def execute(
        self, command: RecordReviewDecisionCommand
    ) -> ReviewDecisionRecord:
        now = self._services.clock.now()
        if command.decision is ReviewDecision.ADJUDICATE:
            raise ValidationError(
                "an adjudication is recorded through the adjudication operation",
                details={"decision": command.decision.value},
            )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            record, _ = await load_authorized_interpretation(
                self._services,
                repositories,
                command.actor,
                interpretation_id=command.interpretation_id,
                action=INTERPRETATION_REVIEW,
                recorder=recorder,
                occurred_at=now,
            )
            require_not_finalized(record.state, interpretation_id=record.id)
            _require_fresh(record, command.expected_current_version_number)
            version = await repositories.interpretations.get_version(
                command.interpretation_version_id
            )
            if version is None or version.interpretation_id != record.id:
                raise NotFoundError(
                    "interpretation version", command.interpretation_version_id
                )
            assignment = await repositories.reviews.find_assignment(
                interpretation_id=record.id,
                reviewer_user_id=command.actor.actor_id,
                review_round=_current_round(record),
            )
            if assignment is None:
                # Holding the review permission is not the same as being one of the
                # reviewers of *this* interpretation.
                raise ConflictError(
                    "you are not assigned to review this interpretation",
                    details={"interpretation_id": record.id},
                )
            if assignment.state in {ReviewState.SUBMITTED, ReviewState.WITHDRAWN}:
                raise ConflictError(
                    "this review is already closed; a further decision needs a new round",
                    details={"review_assignment_id": assignment.id},
                )

            decision = ReviewDecisionRecord(
                id=new_id("rdec"),
                interpretation_id=record.id,
                interpretation_version_id=version.id,
                reviewer_user_id=command.actor.actor_id,
                decision=command.decision,
                decided_at=now,
                decision_role=ClassificationDecisionRole.REVIEWER_DECISION,
                review_assignment_id=assignment.id,
                criterion_evaluation_id=command.criterion_evaluation_id,
                proposed_classification=command.proposed_classification,
                previous_classification=version.classification,
                rationale=command.rationale,
                review_round=assignment.review_round,
                details=dict(command.details or {}),
                created_at=now,
            )
            stored = await repositories.reviews.add_decision(decision)

            if assignment.state is ReviewState.ASSIGNED:
                check_review_transition(assignment.state, ReviewState.IN_PROGRESS)
                await repositories.reviews.save_assignment(
                    assignment.with_state(ReviewState.IN_PROGRESS)
                )

            await recorder.audit(
                action="review_decision.recorded",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="review_decision",
                resource_id=stored.id,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                detail={
                    "interpretation_id": record.id,
                    "interpretation_version_id": version.id,
                    "decision": stored.decision.value,
                    "criterion_evaluation_id": stored.criterion_evaluation_id,
                    "proposed_classification": (
                        stored.proposed_classification.value
                        if stored.proposed_classification
                        else None
                    ),
                },
            )
            await recorder.event(
                event_type=EventType.REVIEW_DECISION_RECORDED,
                aggregate_type="interpretation",
                aggregate_id=record.id,
                occurred_at=now,
                payload={
                    "review_decision_id": stored.id,
                    "decision": stored.decision.value,
                    "review_round": stored.review_round,
                },
            )
            return stored


class SubmitReview:
    """Close the acting reviewer's own assignment for the current round.

    When the last open assignment of the round closes, the submitted proposals are
    compared. Agreement moves the interpretation to APPROVED; disagreement moves it to
    ADJUDICATION and records the disagreement. Nothing averages, breaks ties or drops
    a dissenting proposal.
    """

    def __init__(self, services: ReviewServices) -> None:
        self._services = services

    async def execute(self, command: SubmitReviewCommand) -> ReviewAssignmentRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            record, _ = await load_authorized_interpretation(
                self._services,
                repositories,
                command.actor,
                interpretation_id=command.interpretation_id,
                action=INTERPRETATION_REVIEW,
                recorder=recorder,
                occurred_at=now,
            )
            require_not_finalized(record.state, interpretation_id=record.id)
            review_round = _current_round(record)
            assignment = await repositories.reviews.find_assignment(
                interpretation_id=record.id,
                reviewer_user_id=command.actor.actor_id,
                review_round=review_round,
            )
            if assignment is None:
                raise ConflictError(
                    "you are not assigned to review this interpretation",
                    details={"interpretation_id": record.id},
                )
            check_review_transition(assignment.state, ReviewState.SUBMITTED)
            submitted = await repositories.reviews.save_assignment(
                assignment.with_state(ReviewState.SUBMITTED, completed_at=now)
            )

            assignments = await repositories.reviews.list_assignments(
                interpretation_id=record.id, review_round=review_round
            )
            reviewers = tuple(
                item for item in assignments if item.review_role == REVIEWER_ROLE
            )
            outstanding = tuple(
                item
                for item in reviewers
                if item.state
                not in {ReviewState.SUBMITTED, ReviewState.WITHDRAWN, ReviewState.ACCEPTED}
            )
            if outstanding:
                return submitted

            decisions = await repositories.reviews.list_decisions(
                interpretation_id=record.id, review_round=review_round
            )
            groups = disagreement_between(
                (item.reviewer_user_id, item.proposed_classification)
                for item in decisions
                if item.decision is not ReviewDecision.ABSTAIN
            )
            if len(groups) > 1:
                check_interpretation_transition(
                    record.state, InterpretationState.ADJUDICATION
                )
                await repositories.interpretations.save(
                    record.with_state(
                        InterpretationState.ADJUDICATION,
                        review_state=ReviewState.ESCALATED,
                    )
                )
                await recorder.event(
                    event_type=EventType.REVIEW_DISAGREEMENT_DETECTED,
                    aggregate_type="interpretation",
                    aggregate_id=record.id,
                    occurred_at=now,
                    payload={
                        "review_round": review_round,
                        "proposals": {
                            classification: list(reviewers)
                            for classification, reviewers in groups.items()
                        },
                    },
                )
            else:
                check_interpretation_transition(record.state, InterpretationState.APPROVED)
                await repositories.interpretations.save(
                    record.with_state(
                        InterpretationState.APPROVED, review_state=ReviewState.ACCEPTED
                    )
                )
                await recorder.event(
                    event_type=EventType.INTERPRETATION_STATE_CHANGED,
                    aggregate_type="interpretation",
                    aggregate_id=record.id,
                    occurred_at=now,
                    payload={
                        "state": InterpretationState.APPROVED.value,
                        "review_round": review_round,
                    },
                )
            await recorder.audit(
                action="review.submitted",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="review_assignment",
                resource_id=submitted.id,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                detail={
                    "interpretation_id": record.id,
                    "review_round": review_round,
                    "distinct_proposals": len(groups),
                },
            )
            return submitted


def _current_round(record: InterpretationRecord) -> int:
    return max(1, record.current_version_number)


def _require_fresh(record: InterpretationRecord, expected: int | None) -> None:
    """Refuse a decision written against a version the author has moved past."""
    if expected is not None and expected != record.current_version_number:
        raise ConflictError(
            "this interpretation changed since you loaded it; reload and review again",
            details={
                "interpretation_id": record.id,
                "current_version_number": record.current_version_number,
            },
        )


__all__ = [
    "ADJUDICATOR_ROLE",
    "REVIEWER_ROLE",
    "AssignReviewer",
    "AssignReviewerCommand",
    "RecordReviewDecision",
    "RecordReviewDecisionCommand",
    "SubmitReview",
    "SubmitReviewCommand",
]
