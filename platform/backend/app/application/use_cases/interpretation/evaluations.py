"""Requesting and submitting automated classification evaluations.

The chain, and why it has these steps:

``RequestClassificationEvaluation``
  → the ruleset version is read from the registry and must be *usable*; a retired
    or invalidated version cannot start new work, though its historical results
    stay readable;
  → the evidence selection is resolved through the evidence layer under the
    actor's own readable scope, so an evaluation can only ever consider evidence
    the actor could already read, and the resolved identifiers are frozen onto the
    evaluation;
  → an input digest over ruleset configuration + evidence selection + context is
    recorded, which is what makes "same question, same answer" checkable later;
  → a durable ``classification_evaluation`` job is enqueued in the same
    transaction.

``SubmitClassificationEvaluation`` (the job handler's use case)
  → the existing scientific gateway is asked for the ruleset's declared
    capability, with structured data only: ruleset identity, its stored criteria
    and combination rules, the variant and its gene/disease context, the reference
    context and the authorized evidence references. No command, no script, no
    expression, and no scientific decision is expressed here.

Nothing in this module evaluates a criterion, combines criteria, scores a variant
or decides a classification.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.interpretation.dependencies import (
    CLASSIFICATION_EXECUTE,
    CLASSIFICATION_READ,
    InterpretationServices,
    readable_workspace_scope,
    resolve_scope,
)
from app.domain.analysis.policies import default_queue_for, node_class_for
from app.domain.authorization.context import ActorContext
from app.domain.errors import (
    ConflictError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)
from app.domain.events import EventType
from app.domain.interpretation.entities import (
    AutomatedClassificationRecord,
    ClassificationEvaluationRecord,
    CriterionEvaluationRecord,
    RulesetRecord,
    configuration_digest,
)
from app.domain.value_objects.enums import (
    AuditOutcome,
    ClassificationEvaluationState,
    JobKind,
)
from app.infrastructure.persistence.repositories.base import new_id
from app.scientific.contracts import ExecutionStatus, ScientificExecutionRequest
from app.scientific.interpretation import (
    DEFAULT_INTERPRETATION_CAPABILITY,
    EvidenceReference,
    InterpretationRequestSpecification,
    RulesetIdentity,
)

EVALUATION_JOB_KIND = JobKind.CLASSIFICATION_EVALUATION

FAILURE_SUBMISSION = "scientific_submission_failed"
FAILURE_REJECTED = "scientific_execution_rejected"


@dataclass(frozen=True, slots=True)
class RequestEvaluationCommand:
    actor: ActorContext
    request: RequestContext
    workspace_id: str
    variant_id: str
    ruleset_id: str
    project_id: str | None = None
    gene_symbol: str | None = None
    transcript_identifier: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None
    inheritance: str | None = None
    #: Restricts the evidence selection. Omitted means every evidence record the
    #: actor may read for this variant.
    evidence_ids: tuple[str, ...] | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EvaluationView:
    evaluation: ClassificationEvaluationRecord
    classification: AutomatedClassificationRecord | None = None
    criteria: tuple[CriterionEvaluationRecord, ...] = ()


def evidence_reference_of(record: Any) -> EvidenceReference:
    """Project one stored evidence record onto the contract's reference shape."""
    return EvidenceReference(
        evidence_id=record.id,
        category=_value(record.category),
        direction=_value(record.direction),
        strength=_value(record.strength),
        applicability=_value(record.applicability),
        source_key=record.source_key,
        source_version=record.source_version,
        source_identifier=record.source_identifier,
        summary=record.summary,
    )


def _value(candidate: Any) -> str:
    return getattr(candidate, "value", candidate) or ""


def _input_digest(
    ruleset: RulesetRecord,
    *,
    variant_id: str,
    evidence_ids: tuple[str, ...],
    condition_identifier: str | None,
    gene_symbol: str | None,
    transcript_identifier: str | None,
    inheritance: str | None,
) -> str:
    return configuration_digest(
        {
            "ruleset_key": ruleset.ruleset_key,
            "ruleset_version": ruleset.version,
            "configuration_digest": ruleset.configuration_digest,
            "variant_id": variant_id,
            "evidence_ids": sorted(evidence_ids),
            "condition_identifier": condition_identifier,
            "gene_symbol": gene_symbol,
            "transcript_identifier": transcript_identifier,
            "inheritance": inheritance,
        }
    )


class RequestClassificationEvaluation:
    """Request one automated evaluation of one variant under one ruleset version."""

    def __init__(self, services: InterpretationServices) -> None:
        self._services = services

    async def execute(self, command: RequestEvaluationCommand) -> EvaluationView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            scope = await resolve_scope(
                self._services,
                repositories,
                command.actor,
                workspace_id=command.workspace_id,
                project_id=command.project_id,
                action=CLASSIFICATION_EXECUTE,
                recorder=recorder,
                occurred_at=now,
            )
            if command.idempotency_key:
                existing = await repositories.classification_evaluations.get_by_idempotency_key(
                    workspace_id=scope.workspace_id,
                    idempotency_key=command.idempotency_key,
                )
                if existing is not None:
                    return EvaluationView(evaluation=existing)

            variant = await repositories.variants.get(command.variant_id)
            if variant is None:
                raise NotFoundError("variant", command.variant_id)

            ruleset = await repositories.rulesets.get(command.ruleset_id)
            if ruleset is None:
                raise NotFoundError("interpretation_ruleset", command.ruleset_id)
            if not ruleset.is_usable:
                # A withdrawn guideline version must not produce new suggestions.
                raise ConflictError(
                    "this ruleset version is not usable for new evaluations",
                    details={"state": ruleset.state.value},
                )
            if (
                ruleset.gene_symbol
                and command.gene_symbol
                and ruleset.gene_symbol != command.gene_symbol
            ):
                raise ConflictError(
                    "this specification applies to a different gene",
                    details={
                        "ruleset_gene_symbol": ruleset.gene_symbol,
                        "requested_gene_symbol": command.gene_symbol,
                    },
                )

            # Evidence is resolved under the actor's own readable scope, so an
            # evaluation can never widen what the actor may see.
            readable = frozenset(
                readable_workspace_scope(
                    scope.actor, workspace_id=scope.workspace_id, action=CLASSIFICATION_READ
                )
                or (scope.workspace_id,)
            )
            available = await repositories.evidence_records.list_for_variant(
                variant_id=command.variant_id, workspace_ids=readable
            )
            by_id = {record.id: record for record in available}
            if command.evidence_ids is None:
                selected = tuple(by_id)
            else:
                missing = [
                    candidate
                    for candidate in command.evidence_ids
                    if candidate not in by_id
                ]
                if missing:
                    # Unreadable and non-existent are the same answer on purpose.
                    raise NotFoundError("evidence_record", missing[0])
                selected = tuple(dict.fromkeys(command.evidence_ids))
            if not selected:
                raise ValidationError(
                    "an evaluation requires at least one evidence record",
                    details={"variant_id": command.variant_id},
                )

            evaluation = ClassificationEvaluationRecord(
                id=new_id("cev"),
                workspace_id=scope.workspace_id,
                variant_id=command.variant_id,
                ruleset_id=ruleset.id,
                ruleset_key=ruleset.ruleset_key,
                ruleset_version=ruleset.version,
                state=ClassificationEvaluationState.REQUESTED,
                project_id=scope.project_id,
                gene_symbol=command.gene_symbol or ruleset.gene_symbol,
                transcript_identifier=command.transcript_identifier,
                condition_identifier=command.condition_identifier
                or ruleset.condition_identifier,
                condition_term=command.condition_term or ruleset.condition_term,
                inheritance=command.inheritance,
                genome_assembly=ruleset.genome_assembly
                or getattr(variant, "genome_assembly", None),
                evidence_ids=selected,
                input_digest=_input_digest(
                    ruleset,
                    variant_id=command.variant_id,
                    evidence_ids=selected,
                    condition_identifier=command.condition_identifier,
                    gene_symbol=command.gene_symbol,
                    transcript_identifier=command.transcript_identifier,
                    inheritance=command.inheritance,
                ),
                configuration_digest=ruleset.configuration_digest,
                capability_id=ruleset.capability_id or DEFAULT_INTERPRETATION_CAPABILITY,
                capability_version=ruleset.capability_version,
                engine_resource_id=ruleset.engine_resource_id,
                correlation_id=command.request.correlation_id,
                idempotency_key=command.idempotency_key,
                requested_by=scope.actor.actor_id,
                requested_at=now,
                metadata=dict(command.metadata or {}),
                created_at=now,
            )
            stored = await repositories.classification_evaluations.add(evaluation)

            job_id = await repositories.jobs.enqueue(
                kind=EVALUATION_JOB_KIND,
                payload={"classification_evaluation_id": stored.id},
                correlation_id=command.request.correlation_id,
                queue=default_queue_for(EVALUATION_JOB_KIND).value,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                idempotency_key=f"classification-evaluation:{stored.id}",
                node_class=node_class_for(EVALUATION_JOB_KIND),
            )
            stored = await repositories.classification_evaluations.save(
                replace(stored, job_id=job_id)
            )

            await recorder.audit(
                action="classification_evaluation.requested",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="classification_evaluation",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                new_state=stored.state.value,
                detail={
                    "variant_id": stored.variant_id,
                    "ruleset_key": stored.ruleset_key,
                    "ruleset_version": stored.ruleset_version,
                    "evidence_count": len(stored.evidence_ids),
                    "input_digest": stored.input_digest,
                },
            )
            await recorder.event(
                event_type=EventType.CLASSIFICATION_EVALUATION_REQUESTED,
                aggregate_type="classification_evaluation",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
                payload={
                    "variant_id": stored.variant_id,
                    "ruleset_id": stored.ruleset_id,
                    "capability_id": stored.capability_id,
                },
            )
            return EvaluationView(evaluation=stored)


class SubmitClassificationEvaluation:
    """Submit a requested evaluation to the rules engine through the gateway.

    Called by the ``classification_evaluation`` job handler, never from a request.
    """

    def __init__(self, services: InterpretationServices) -> None:
        self._services = services

    async def execute(
        self, *, classification_evaluation_id: str, request: RequestContext
    ) -> ClassificationEvaluationRecord:
        if self._services.scientific is None:
            raise InfrastructureError("the scientific gateway is not configured")
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            evaluation = await repositories.classification_evaluations.get(
                classification_evaluation_id
            )
            if evaluation is None:
                raise NotFoundError(
                    "classification_evaluation", classification_evaluation_id
                )
            if (
                evaluation.is_terminal
                or evaluation.state is not ClassificationEvaluationState.REQUESTED
            ):
                # Job retries must not resubmit work that already moved on.
                return evaluation
            ruleset = await repositories.rulesets.get(evaluation.ruleset_id)
            if ruleset is None:
                raise NotFoundError("interpretation_ruleset", evaluation.ruleset_id)
            evidence = tuple(
                record
                for record in (
                    await repositories.evidence_records.list_for_variant(
                        variant_id=evaluation.variant_id,
                        workspace_ids=frozenset({evaluation.workspace_id}),
                        include_superseded=True,
                    )
                )
                if record.id in set(evaluation.evidence_ids)
            )
            variant = await repositories.variants.get(evaluation.variant_id)

        specification = InterpretationRequestSpecification(
            evaluation_id=evaluation.id,
            ruleset=RulesetIdentity(
                ruleset_key=ruleset.ruleset_key,
                ruleset_version=ruleset.version,
                ruleset_id=ruleset.id,
                guideline_source=ruleset.guideline_source,
                specification_scope=ruleset.specification_scope.value,
                configuration_digest=ruleset.configuration_digest,
            ),
            variant_id=evaluation.variant_id,
            variant_identifier=getattr(variant, "canonical_identifier", None),
            genome_assembly=evaluation.genome_assembly,
            reference_genome_resource_id=evaluation.reference_genome_resource_id,
            gene_symbol=evaluation.gene_symbol,
            transcript_identifier=evaluation.transcript_identifier,
            condition_identifier=evaluation.condition_identifier,
            condition_term=evaluation.condition_term,
            inheritance=evaluation.inheritance,
            evidence=tuple(evidence_reference_of(record) for record in evidence),
            criteria=tuple(
                item
                for item in ruleset.digest_payload().get("criteria", [])
            ),
            combination_rules=tuple(
                item for item in ruleset.digest_payload().get("combination_rules", [])
            ),
            combination_strategy=ruleset.combination_strategy.value,
            provenance_context={
                "workspace_id": evaluation.workspace_id,
                "project_id": evaluation.project_id,
                "requested_by": evaluation.requested_by,
                "requested_at": evaluation.requested_at.isoformat()
                if evaluation.requested_at
                else None,
                "input_digest": evaluation.input_digest,
                "software_version": self._services.software_version,
            },
        )
        execution_request = ScientificExecutionRequest(
            capability_id=evaluation.capability_id or DEFAULT_INTERPRETATION_CAPABILITY,
            capability_version=evaluation.capability_version,
            correlation_id=evaluation.correlation_id or request.correlation_id,
            inputs=(),
            parameters=specification.as_parameters(),
        )

        try:
            response = await self._services.scientific.submit_execution(
                execution_request
            )
        except Exception as error:
            async with self._services.unit_of_work.begin() as repositories:
                recorder = ActivityRecorder(repositories, request)
                failed = await repositories.classification_evaluations.save(
                    evaluation.transition_to(
                        ClassificationEvaluationState.FAILED,
                        at=now,
                        failure_code=FAILURE_SUBMISSION,
                        failure_message=str(error),
                    )
                )
                await self._record_failure(recorder, failed, now=now)
            raise

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            current = (
                await repositories.classification_evaluations.get(evaluation.id)
                or evaluation
            )
            if response.status is ExecutionStatus.FAILED:
                failure = response.failure
                stored = await repositories.classification_evaluations.save(
                    current.transition_to(
                        ClassificationEvaluationState.FAILED,
                        at=now,
                        failure_code=failure.code if failure else FAILURE_REJECTED,
                        failure_message=failure.message
                        if failure
                        else "execution failed",
                    )
                )
                await self._record_failure(recorder, stored, now=now)
                return stored
            if response.status is ExecutionStatus.CANCELLED:
                return await repositories.classification_evaluations.save(
                    current.transition_to(
                        ClassificationEvaluationState.CANCELLED, at=now
                    )
                )

            provenance = response.provenance
            stored = current.transition_to(
                ClassificationEvaluationState.SUBMITTED, at=now
            )
            stored = replace(
                stored,
                scientific_execution_id=response.execution_id,
                engine_resource_id=(
                    provenance.engine.engine_id
                    if provenance
                    else stored.engine_resource_id
                ),
                engine_version=(
                    provenance.engine.engine_version
                    if provenance
                    else stored.engine_version
                ),
                environment_version=(
                    provenance.environment.environment_version if provenance else None
                ),
                container_image_digest=(
                    provenance.environment.container_digest if provenance else None
                ),
            )
            stored = await repositories.classification_evaluations.save(stored)
            await recorder.audit(
                action="classification_evaluation.submitted",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                resource_type="classification_evaluation",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                new_state=stored.state.value,
                detail={
                    "scientific_execution_id": stored.scientific_execution_id,
                    "capability_id": stored.capability_id,
                },
            )
            await recorder.event(
                event_type=EventType.CLASSIFICATION_EVALUATION_SUBMITTED,
                aggregate_type="classification_evaluation",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
                payload={"scientific_execution_id": stored.scientific_execution_id},
            )
            return stored

    async def _record_failure(
        self,
        recorder: ActivityRecorder,
        evaluation: ClassificationEvaluationRecord,
        *,
        now,
    ) -> None:
        await recorder.audit(
            action="classification_evaluation.failed",
            outcome=AuditOutcome.FAILURE,
            occurred_at=now,
            resource_type="classification_evaluation",
            resource_id=evaluation.id,
            workspace_id=evaluation.workspace_id,
            project_id=evaluation.project_id,
            new_state=evaluation.state.value,
            detail={
                "failure_code": evaluation.failure_code,
                "failure_message": evaluation.failure_message,
            },
        )
        await recorder.event(
            event_type=EventType.CLASSIFICATION_EVALUATION_FAILED,
            aggregate_type="classification_evaluation",
            aggregate_id=evaluation.id,
            occurred_at=now,
            workspace_id=evaluation.workspace_id,
            payload={"failure_code": evaluation.failure_code},
        )


@dataclass(frozen=True, slots=True)
class ClassificationReader:
    """Reads of evaluations and the suggestions they produced.

    Every read is scoped by the stored row's own workspace, and the history is
    returned complete: a superseded suggestion stays visible, because hiding it
    would hide that the automated answer changed.
    """

    services: InterpretationServices

    async def list_evaluations(
        self,
        actor: ActorContext,
        request: RequestContext,
        *,
        page: Page,
        workspace_id: str | None = None,
        variant_id: str | None = None,
        ruleset_id: str | None = None,
        project_id: str | None = None,
        state: ClassificationEvaluationState | None = None,
    ) -> Paged[ClassificationEvaluationRecord]:
        async with self.services.unit_of_work.begin() as repositories:
            scope = readable_workspace_scope(actor, workspace_id=workspace_id)
            if not scope:
                return Paged(items=(), total=0, page=page)
            return await repositories.classification_evaluations.list_evaluations(
                page=page,
                workspace_ids=frozenset(scope),
                variant_id=variant_id,
                ruleset_id=ruleset_id,
                project_id=project_id,
                state=state,
            )

    async def get(
        self,
        actor: ActorContext,
        request: RequestContext,
        *,
        classification_evaluation_id: str,
    ) -> EvaluationView:
        now = self.services.clock.now()
        async with self.services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            evaluation = await repositories.classification_evaluations.get(
                classification_evaluation_id
            )
            if evaluation is None:
                raise NotFoundError(
                    "classification_evaluation", classification_evaluation_id
                )
            await resolve_scope(
                self.services,
                repositories,
                actor,
                workspace_id=evaluation.workspace_id,
                project_id=evaluation.project_id,
                action=CLASSIFICATION_READ,
                recorder=recorder,
                occurred_at=now,
            )
            classification = (
                await repositories.classification_evaluations.get_classification(
                    evaluation.classification_id
                )
                if evaluation.classification_id
                else None
            )
            criteria = (
                await repositories.classification_evaluations.list_criterion_evaluations(
                    classification_evaluation_id=evaluation.id
                )
            )
            return EvaluationView(
                evaluation=evaluation, classification=classification, criteria=criteria
            )

    async def history_for_variant(
        self,
        actor: ActorContext,
        request: RequestContext,
        *,
        variant_id: str,
        ruleset_id: str | None = None,
        limit: int = 100,
    ) -> tuple[AutomatedClassificationRecord, ...]:
        async with self.services.unit_of_work.begin() as repositories:
            scope = readable_workspace_scope(actor)
            if not scope:
                return ()
            return await repositories.classification_evaluations.classification_history(
                variant_id=variant_id,
                workspace_ids=frozenset(scope),
                ruleset_id=ruleset_id,
                limit=limit,
            )


__all__ = [
    "ClassificationReader",
    "EvaluationView",
    "RequestClassificationEvaluation",
    "RequestEvaluationCommand",
    "SubmitClassificationEvaluation",
    "evidence_reference_of",
]
