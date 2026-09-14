"""Adjudication of reviewer disagreement, and finalization of an interpretation.

Adjudication resolves a disagreement by *adding* a record: a new interpretation
version carrying the adjudicated decision, an append-only adjudication decision row
naming the reviewer decisions it resolved, and a stored summary of the disagreement as
it stood. The original reviewer decisions keep their rows unchanged — the history of a
disagreement survives its resolution, which is the whole point.

Finalization closes the current version: it stamps the final decision role and the
finalizer, moves the interpretation to FINALIZED, and from then on the version is
immutable. A correction is a new interpretation version recorded through
reclassification, which supersedes rather than rewrites.

Adjudicating and finalizing are separate permissions from reviewing, so a reviewer who
took part in a disagreement does not get to rule on it merely by being a reviewer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.review.dependencies import (
    INTERPRETATION_ADJUDICATE,
    INTERPRETATION_FINALIZE,
    ReviewServices,
    load_authorized_interpretation,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, ValidationError
from app.domain.events import EventType
from app.domain.review.entities import (
    InterpretationVersionRecord,
    ReviewDecisionRecord,
)
from app.domain.review.workflow import (
    check_interpretation_transition,
    disagreement_between,
    require_not_finalized,
)
from app.domain.value_objects.enums import (
    AuditOutcome,
    Classification,
    ClassificationDecisionRole,
    DataOrigin,
    InterpretationState,
    ReviewDecision,
)
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class AdjudicateInterpretationCommand:
    actor: ActorContext
    request: RequestContext
    interpretation_id: str
    classification: Classification
    rationale: str
    clinical_significance_statement: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class FinalizeInterpretationCommand:
    actor: ActorContext
    request: RequestContext
    interpretation_id: str
    #: Reasoning for closing the record. Required: a final clinical decision without
    #: recorded reasoning is not a usable scientific record.
    rationale: str
    expected_version_number: int | None = None


class AdjudicateInterpretation:
    """Resolve reviewer disagreement by recording an adjudicated decision."""

    def __init__(self, services: ReviewServices) -> None:
        self._services = services

    async def execute(
        self, command: AdjudicateInterpretationCommand
    ) -> InterpretationVersionRecord:
        now = self._services.clock.now()
        if not (command.rationale or "").strip():
            raise ValidationError(
                "an adjudication must record why the disagreement was resolved this way",
                details={"field": "rationale"},
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
            if record.state is not InterpretationState.ADJUDICATION:
                raise ConflictError(
                    "this interpretation is not awaiting adjudication",
                    details={"interpretation_id": record.id, "state": record.state.value},
                )
            review_round = max(1, record.current_version_number)
            decisions = await repositories.reviews.list_decisions(
                interpretation_id=record.id, review_round=review_round
            )
            reviewer_decisions = tuple(
                item
                for item in decisions
                if item.decision_role is ClassificationDecisionRole.REVIEWER_DECISION
            )
            groups = disagreement_between(
                (item.reviewer_user_id, item.proposed_classification)
                for item in reviewer_decisions
                if item.decision is not ReviewDecision.ABSTAIN
            )
            current = (
                await repositories.interpretations.get_version(record.current_version_id)
                if record.current_version_id
                else None
            )
            disagreement_summary = {
                "review_round": review_round,
                "proposals": {
                    classification: list(reviewers)
                    for classification, reviewers in groups.items()
                },
                "resolved_decision_ids": [item.id for item in reviewer_decisions],
            }
            version_number = record.current_version_number + 1
            version = InterpretationVersionRecord(
                id=new_id("intv"),
                interpretation_id=record.id,
                version_number=version_number,
                classification=command.classification,
                origin=DataOrigin.HUMAN_EVALUATED,
                decision_role=ClassificationDecisionRole.ADJUDICATED_DECISION,
                suggested_classification=(
                    current.suggested_classification if current else None
                ),
                rationale=command.rationale,
                clinical_significance_statement=command.clinical_significance_statement,
                ruleset_id=current.ruleset_id if current else None,
                ruleset_version=current.ruleset_version if current else None,
                classification_evaluation_id=(
                    current.classification_evaluation_id if current else None
                ),
                automated_classification_id=(
                    current.automated_classification_id if current else None
                ),
                # The adjudicated decision rests on exactly the criterion evaluations
                # and evidence versions the reviewers were looking at.
                criterion_evaluation_ids=(
                    current.criterion_evaluation_ids if current else ()
                ),
                evidence_item_ids=current.evidence_item_ids if current else (),
                disagreement_summary=disagreement_summary,
                review_round=review_round,
                authored_by=command.actor.actor_id,
                adjudicated_by=command.actor.actor_id,
                adjudicated_at=now,
                supersedes_version_id=record.current_version_id,
                created_at=now,
            )
            stored = await repositories.interpretations.add_version(version)

            adjudication = ReviewDecisionRecord(
                id=new_id("rdec"),
                interpretation_id=record.id,
                interpretation_version_id=stored.id,
                reviewer_user_id=command.actor.actor_id,
                decision=ReviewDecision.ADJUDICATE,
                decided_at=now,
                decision_role=ClassificationDecisionRole.ADJUDICATED_DECISION,
                proposed_classification=command.classification,
                previous_classification=current.classification if current else None,
                rationale=command.rationale,
                review_round=review_round,
                is_adjudication=True,
                resolves_decision_id=(
                    reviewer_decisions[0].id if reviewer_decisions else None
                ),
                details=dict(command.details or {}) | disagreement_summary,
                created_at=now,
            )
            await repositories.reviews.add_decision(adjudication)

            check_interpretation_transition(record.state, InterpretationState.APPROVED)
            await repositories.interpretations.save(
                record.with_current_version(
                    version_id=stored.id, version_number=version_number
                ).with_state(InterpretationState.APPROVED)
            )

            await recorder.audit(
                action="interpretation.adjudicated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="interpretation_version",
                resource_id=stored.id,
                previous_state=record.state.value,
                new_state=InterpretationState.APPROVED.value,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                detail={
                    "interpretation_id": record.id,
                    "classification": stored.classification.value,
                    "distinct_proposals": len(groups),
                },
            )
            await recorder.event(
                event_type=EventType.REVIEW_ADJUDICATED,
                aggregate_type="interpretation",
                aggregate_id=record.id,
                occurred_at=now,
                payload={
                    "interpretation_version_id": stored.id,
                    "classification": stored.classification.value,
                    "review_round": review_round,
                },
            )
            return stored


class FinalizeInterpretation:
    """Close the current version as the final interpretation."""

    def __init__(self, services: ReviewServices) -> None:
        self._services = services

    async def execute(
        self, command: FinalizeInterpretationCommand
    ) -> InterpretationVersionRecord:
        now = self._services.clock.now()
        if not (command.rationale or "").strip():
            raise ValidationError(
                "finalizing an interpretation requires a recorded rationale",
                details={"field": "rationale"},
            )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            record, _ = await load_authorized_interpretation(
                self._services,
                repositories,
                command.actor,
                interpretation_id=command.interpretation_id,
                action=INTERPRETATION_FINALIZE,
                recorder=recorder,
                occurred_at=now,
            )
            require_not_finalized(record.state, interpretation_id=record.id)
            if record.state is not InterpretationState.APPROVED:
                raise ConflictError(
                    "only an approved interpretation can be finalized",
                    details={"interpretation_id": record.id, "state": record.state.value},
                )
            if (
                command.expected_version_number is not None
                and command.expected_version_number != record.current_version_number
            ):
                raise ConflictError(
                    "this interpretation changed since you loaded it",
                    details={
                        "current_version_number": record.current_version_number,
                    },
                )
            current = (
                await repositories.interpretations.get_version(record.current_version_id)
                if record.current_version_id
                else None
            )
            if current is None:
                raise ConflictError(
                    "this interpretation has no version to finalize",
                    details={"interpretation_id": record.id},
                )
            finalized = await repositories.interpretations.finalize_version(
                current.finalized(by=command.actor.actor_id, at=now)
            )
            check_interpretation_transition(record.state, InterpretationState.FINALIZED)
            await repositories.interpretations.save(
                record.with_state(InterpretationState.FINALIZED)
            )

            await recorder.audit(
                action="interpretation.finalized",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="interpretation_version",
                resource_id=finalized.id,
                previous_state=record.state.value,
                new_state=InterpretationState.FINALIZED.value,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                detail={
                    "interpretation_id": record.id,
                    "classification": finalized.classification.value,
                    "version_number": finalized.version_number,
                    "rationale": command.rationale,
                },
            )
            await recorder.event(
                event_type=EventType.INTERPRETATION_FINALIZED,
                aggregate_type="interpretation",
                aggregate_id=record.id,
                occurred_at=now,
                payload={
                    "interpretation_version_id": finalized.id,
                    "classification": finalized.classification.value,
                },
            )
            return finalized


__all__ = [
    "AdjudicateInterpretation",
    "AdjudicateInterpretationCommand",
    "FinalizeInterpretation",
    "FinalizeInterpretationCommand",
]
