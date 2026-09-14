"""Opening interpretations and recording immutable interpretation versions.

``OpenInterpretation``
  → creates the decision context for one variant in one project, optionally in one
    disease/gene context, and refuses a duplicate context for the same variant so
    two parallel decision records cannot exist for the same question.

``RecordInterpretationVersion``
  → appends a new version. It pins the exact criterion evaluations, the exact
    evidence item versions, the ruleset version and the automated suggestion the
    decision was made against, and it refuses to write against a finalized
    interpretation — a correction has to be a new version, which is exactly what
    this use case produces.

The classification carried by a version is a *decision that a person recorded*, not
a value this module derived. Nothing here evaluates a criterion or combines criteria.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.review.dependencies import (
    INTERPRETATION_AUTHOR,
    INTERPRETATION_READ,
    ReviewServices,
    load_authorized_interpretation,
    readable_workspace_scope,
    require_scope,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.review.entities import (
    InterpretationRecord,
    InterpretationVersionRecord,
    ReviewAssignmentRecord,
    ReviewDecisionRecord,
)
from app.domain.review.workflow import (
    check_interpretation_transition,
    require_not_finalized,
)
from app.domain.value_objects.enums import (
    AuditOutcome,
    Classification,
    ClassificationDecisionRole,
    DataOrigin,
    InterpretationState,
)
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class OpenInterpretationCommand:
    actor: ActorContext
    request: RequestContext
    project_id: str
    variant_id: str
    sample_id: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None


@dataclass(frozen=True, slots=True)
class RecordInterpretationVersionCommand:
    actor: ActorContext
    request: RequestContext
    interpretation_id: str
    classification: Classification
    rationale: str
    #: The automated suggestion this decision started from, if there was one.
    classification_evaluation_id: str | None = None
    automated_classification_id: str | None = None
    ruleset_id: str | None = None
    ruleset_version: str | None = None
    suggested_classification: Classification | None = None
    clinical_significance_statement: str | None = None
    criterion_evaluation_ids: tuple[str, ...] = ()
    evidence_item_ids: tuple[str, ...] = ()
    #: Author role. A version recorded here is a reviewer decision by default; an
    #: adjudication and a finalization are recorded by their own use cases.
    decision_role: ClassificationDecisionRole = (
        ClassificationDecisionRole.REVIEWER_DECISION
    )
    origin: DataOrigin = DataOrigin.HUMAN_EVALUATED
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class InterpretationDetail:
    """Everything the review workspace needs, in one authorized read."""

    interpretation: InterpretationRecord
    versions: tuple[InterpretationVersionRecord, ...]
    assignments: tuple[ReviewAssignmentRecord, ...]
    decisions: tuple[ReviewDecisionRecord, ...]

    @property
    def current_version(self) -> InterpretationVersionRecord | None:
        for version in self.versions:
            if version.id == self.interpretation.current_version_id:
                return version
        return self.versions[0] if self.versions else None


class OpenInterpretation:
    """Open the decision context for one variant in one project."""

    def __init__(self, services: ReviewServices) -> None:
        self._services = services

    async def execute(self, command: OpenInterpretationCommand) -> InterpretationRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            project = await repositories.projects.get(command.project_id)
            if project is None:
                raise NotFoundError("project", command.project_id)
            # Tenancy comes from the project row, never from the request body.
            await require_scope(
                self._services,
                repositories,
                command.actor,
                workspace_id=project.workspace_id,
                project_id=command.project_id,
                action=INTERPRETATION_AUTHOR,
                recorder=recorder,
                occurred_at=now,
            )
            existing = await repositories.interpretations.find_for_context(
                project_id=command.project_id,
                variant_id=command.variant_id,
                condition_identifier=command.condition_identifier,
                sample_id=command.sample_id,
            )
            if existing is not None:
                # Two decision records for the same question would let two
                # different final classifications both look authoritative.
                raise ConflictError(
                    "an interpretation is already open for this variant and context",
                    details={"interpretation_id": existing.id},
                )
            record = InterpretationRecord(
                id=new_id("intp"),
                workspace_id=project.workspace_id,
                project_id=command.project_id,
                variant_id=command.variant_id,
                created_by=command.actor.actor_id,
                sample_id=command.sample_id,
                condition_identifier=command.condition_identifier,
                condition_term=command.condition_term,
                created_at=now,
            )
            stored = await repositories.interpretations.add(record)
            await recorder.audit(
                action="interpretation.opened",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="interpretation",
                resource_id=stored.id,
                new_state=stored.state.value,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                detail={
                    "variant_id": stored.variant_id,
                    "condition_identifier": stored.condition_identifier,
                },
            )
            await recorder.event(
                event_type=EventType.INTERPRETATION_OPENED,
                aggregate_type="interpretation",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={
                    "variant_id": stored.variant_id,
                    "project_id": stored.project_id,
                },
            )
            return stored


class RecordInterpretationVersion:
    """Append an immutable interpretation version.

    Refuses a finalized interpretation outright: the way to change a finalized
    decision is a *new* interpretation, or a reopened one, never an edit.
    """

    def __init__(self, services: ReviewServices) -> None:
        self._services = services

    async def execute(
        self, command: RecordInterpretationVersionCommand
    ) -> InterpretationVersionRecord:
        now = self._services.clock.now()
        if not (command.rationale or "").strip():
            raise ValidationError(
                "an interpretation version must carry the reasoning behind it",
                details={"field": "rationale"},
            )
        if command.decision_role in {
            ClassificationDecisionRole.ADJUDICATED_DECISION,
            ClassificationDecisionRole.FINAL_INTERPRETATION,
        }:
            # Adjudication and finalization are their own authorized operations.
            raise ValidationError(
                "an adjudicated or final decision is recorded through adjudication "
                "and finalization, not by authoring a version",
                details={"decision_role": command.decision_role.value},
            )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            record, _ = await load_authorized_interpretation(
                self._services,
                repositories,
                command.actor,
                interpretation_id=command.interpretation_id,
                action=INTERPRETATION_AUTHOR,
                recorder=recorder,
                occurred_at=now,
            )
            require_not_finalized(record.state, interpretation_id=record.id)
            await _validate_pins(
                repositories,
                criterion_ids=command.criterion_evaluation_ids,
                evidence_ids=command.evidence_item_ids,
                variant_id=record.variant_id,
                classification_evaluation_id=command.classification_evaluation_id,
            )
            version_number = record.current_version_number + 1
            version = InterpretationVersionRecord(
                id=new_id("intv"),
                interpretation_id=record.id,
                version_number=version_number,
                classification=command.classification,
                origin=command.origin,
                decision_role=command.decision_role,
                suggested_classification=command.suggested_classification,
                rationale=command.rationale,
                clinical_significance_statement=(
                    command.clinical_significance_statement
                ),
                ruleset_id=command.ruleset_id,
                ruleset_version=command.ruleset_version,
                classification_evaluation_id=command.classification_evaluation_id,
                automated_classification_id=command.automated_classification_id,
                criterion_evaluation_ids=tuple(command.criterion_evaluation_ids),
                evidence_item_ids=tuple(command.evidence_item_ids),
                evaluation_snapshot=dict(command.metadata or {}),
                review_round=_round_of(record),
                authored_by=command.actor.actor_id,
                supersedes_version_id=record.current_version_id,
                created_at=now,
            )
            stored = await repositories.interpretations.add_version(version)

            target = (
                InterpretationState.AUTOMATED
                if command.automated_classification_id
                and record.state is InterpretationState.DRAFT
                else record.state
            )
            if target is not record.state:
                check_interpretation_transition(record.state, target)
            await repositories.interpretations.save(
                record.with_current_version(
                    version_id=stored.id, version_number=version_number
                ).with_state(target)
            )

            await recorder.audit(
                action="interpretation_version.recorded",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="interpretation_version",
                resource_id=stored.id,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                detail={
                    "interpretation_id": record.id,
                    "version_number": version_number,
                    "classification": stored.classification.value,
                    "decision_role": stored.decision_role.value,
                    "criterion_count": len(stored.criterion_evaluation_ids),
                    "evidence_count": len(stored.evidence_item_ids),
                },
            )
            await recorder.event(
                event_type=EventType.INTERPRETATION_VERSION_RECORDED,
                aggregate_type="interpretation",
                aggregate_id=record.id,
                occurred_at=now,
                payload={
                    "interpretation_version_id": stored.id,
                    "version_number": version_number,
                    "classification": stored.classification.value,
                    "decision_role": stored.decision_role.value,
                },
            )
            return stored


class InterpretationReader:
    """Authorized reads of interpretations and their full decision history."""

    def __init__(self, services: ReviewServices) -> None:
        self._services = services

    async def list_interpretations(
        self,
        actor: ActorContext,
        *,
        page: Page,
        workspace_id: str | None = None,
        project_id: str | None = None,
        variant_id: str | None = None,
        state: InterpretationState | None = None,
        assigned_to_me: bool = False,
    ) -> Paged[InterpretationRecord]:
        scope = readable_workspace_scope(actor, workspace_id=workspace_id)
        if not scope:
            return Paged(items=(), total=0, page=page)
        async with self._services.unit_of_work.begin() as repositories:
            return await repositories.interpretations.list_interpretations(
                page=page,
                workspace_ids=frozenset(scope),
                project_id=project_id,
                variant_id=variant_id,
                state=state,
                reviewer_user_id=actor.actor_id if assigned_to_me else None,
            )

    async def detail(
        self, actor: ActorContext, *, interpretation_id: str, request: RequestContext
    ) -> InterpretationDetail:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            record, _ = await load_authorized_interpretation(
                self._services,
                repositories,
                actor,
                interpretation_id=interpretation_id,
                action=INTERPRETATION_READ,
                recorder=recorder,
                occurred_at=now,
            )
            return InterpretationDetail(
                interpretation=record,
                versions=await repositories.interpretations.list_versions(
                    interpretation_id=record.id
                ),
                assignments=await repositories.reviews.list_assignments(
                    interpretation_id=record.id
                ),
                decisions=await repositories.reviews.list_decisions(
                    interpretation_id=record.id
                ),
            )


@dataclass(frozen=True, slots=True)
class ReclassifyInterpretationCommand:
    actor: ActorContext
    request: RequestContext
    interpretation_id: str
    reason: str


class ReclassifyInterpretation:
    """Reopen a finalized decision as a new, separate interpretation.

    The finalized interpretation becomes SUPERSEDED and keeps every one of its
    versions exactly as they were — a report that cited it keeps meaning what it
    meant. The successor is a fresh decision context for the same variant and
    condition, whose first version will name the superseded version it replaces, so
    the reclassification chain stays walkable in both directions.
    """

    def __init__(self, services: ReviewServices) -> None:
        self._services = services

    async def execute(
        self, command: ReclassifyInterpretationCommand
    ) -> InterpretationRecord:
        now = self._services.clock.now()
        if not (command.reason or "").strip():
            raise ValidationError(
                "a reclassification must record why the finalized decision is "
                "being revisited",
                details={"field": "reason"},
            )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            record, _ = await load_authorized_interpretation(
                self._services,
                repositories,
                command.actor,
                interpretation_id=command.interpretation_id,
                action=INTERPRETATION_AUTHOR,
                recorder=recorder,
                occurred_at=now,
            )
            if record.state is not InterpretationState.FINALIZED:
                raise ConflictError(
                    "only a finalized interpretation is reclassified; an open one is "
                    "revised by recording a new version",
                    details={"interpretation_id": record.id, "state": record.state.value},
                )
            check_interpretation_transition(record.state, InterpretationState.SUPERSEDED)
            await repositories.interpretations.save(
                record.with_state(InterpretationState.SUPERSEDED)
            )
            successor = await repositories.interpretations.add(
                InterpretationRecord(
                    id=new_id("intp"),
                    workspace_id=record.workspace_id,
                    project_id=record.project_id,
                    variant_id=record.variant_id,
                    created_by=command.actor.actor_id,
                    sample_id=record.sample_id,
                    condition_identifier=record.condition_identifier,
                    condition_term=record.condition_term,
                    created_at=now,
                )
            )
            await recorder.audit(
                action="interpretation.reclassified",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="interpretation",
                resource_id=record.id,
                previous_state=InterpretationState.FINALIZED.value,
                new_state=InterpretationState.SUPERSEDED.value,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                detail={
                    "successor_interpretation_id": successor.id,
                    "superseded_version_id": record.current_version_id,
                    "reason": command.reason,
                },
            )
            await recorder.event(
                event_type=EventType.INTERPRETATION_RECLASSIFIED,
                aggregate_type="interpretation",
                aggregate_id=record.id,
                occurred_at=now,
                payload={
                    "successor_interpretation_id": successor.id,
                    "superseded_version_id": record.current_version_id,
                },
            )
            return successor


def _round_of(record: InterpretationRecord) -> int:
    """Current review round, derived from the definition's own progress."""
    return max(1, record.current_version_number)


async def _validate_pins(
    repositories: Any,
    *,
    criterion_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    variant_id: str,
    classification_evaluation_id: str | None = None,
) -> None:
    """Every pinned criterion evaluation and evidence item must exist and match.

    A version that pinned a criterion evaluation from another evaluation, or evidence
    about another variant, would be unreadable as a scientific record later, so it is
    refused rather than stored.
    """
    if criterion_ids:
        if classification_evaluation_id is None:
            raise ValidationError(
                "pinned criterion evaluations must name the classification "
                "evaluation they came from",
                details={"field": "classification_evaluation_id"},
            )
        known = {
            row.id
            for row in await (
                repositories.classification_evaluations.list_criterion_evaluations(
                    classification_evaluation_id=classification_evaluation_id
                )
            )
        }
        unknown = tuple(sorted(set(criterion_ids) - known))
        if unknown:
            raise ValidationError(
                "a pinned criterion evaluation does not belong to the named "
                "classification evaluation",
                details={"criterion_evaluation_ids": list(unknown)},
            )
    for evidence_id in evidence_ids:
        record = await repositories.evidence_records.get(evidence_id)
        if record is None:
            raise NotFoundError("evidence", evidence_id)
        if record.variant_id != variant_id:
            raise ValidationError(
                "an evidence item pinned into this interpretation belongs to a "
                "different variant",
                details={"evidence_id": evidence_id},
            )


__all__ = [
    "InterpretationDetail",
    "InterpretationReader",
    "OpenInterpretation",
    "OpenInterpretationCommand",
    "ReclassifyInterpretation",
    "ReclassifyInterpretationCommand",
    "RecordInterpretationVersion",
    "RecordInterpretationVersionCommand",
]
