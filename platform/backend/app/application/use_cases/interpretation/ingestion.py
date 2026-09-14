"""Ingesting one interpretation payload from the rules engine.

What this does, and equally what it refuses to do:

* validates the payload's attribution and shape against the evaluation and the
  pinned ruleset version — contract version, evaluation identity, ruleset identity
  and configuration digest, criterion existence, permitted strength, evidence
  authorization, declared classification;
* stores the criterion evaluations and the suggested classification exactly as
  produced, with the engine/environment identity that produced them;
* supersedes the previous suggestion for the same ``(variant, ruleset, condition)``
  instead of overwriting it, so the earlier automated answer stays readable and a
  reclassification is visible as a change rather than as a rewrite;
* refuses the whole payload when attribution is broken, recording findings and
  failing the evaluation. It never repairs a scientific value, never recomputes a
  strength and never decides a criterion or classification itself.

Re-delivering the same payload is idempotent: the stored suggestion is returned
unchanged rather than duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.interpretation.dependencies import (
    CLASSIFICATION_EXECUTE,
    InterpretationServices,
    resolve_scope,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import NotFoundError
from app.domain.events import EventType
from app.domain.interpretation.entities import (
    AutomatedClassificationRecord,
    ClassificationEvaluationRecord,
    CriterionEvaluationRecord,
)
from app.domain.interpretation.validation import (
    InterpretationFinding,
    validate_interpretation_payload,
)
from app.domain.value_objects.enums import (
    AuditOutcome,
    Classification,
    ClassificationEvaluationState,
    CriterionDirection,
    CriterionStrength,
    DataOrigin,
)
from app.infrastructure.persistence.repositories.base import new_id
from app.scientific.interpretation import InterpretationPayload

FAILURE_PAYLOAD_REJECTED = "interpretation_payload_rejected"


@dataclass(frozen=True, slots=True)
class IngestInterpretationCommand:
    request: RequestContext
    payload: InterpretationPayload
    #: Present for a user-driven delivery; absent when a worker ingests.
    actor: ActorContext | None = None
    service_account_id: str | None = None
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    evaluation: ClassificationEvaluationRecord
    classification: AutomatedClassificationRecord | None = None
    criteria: tuple[CriterionEvaluationRecord, ...] = ()
    findings: tuple[InterpretationFinding, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.classification is not None


class IngestInterpretationPayload:
    """Validate, store and version one automated classification payload."""

    def __init__(self, services: InterpretationServices) -> None:
        self._services = services

    async def execute(self, command: IngestInterpretationCommand) -> IngestionResult:
        payload = command.payload
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            evaluation = await repositories.classification_evaluations.get(
                payload.evaluation_id
            )
            if evaluation is None:
                raise NotFoundError("classification_evaluation", payload.evaluation_id)

            # Scope comes from the evaluation row, never from the payload: a
            # producer cannot address a workspace it was not run for.
            if command.actor is not None:
                await resolve_scope(
                    self._services,
                    repositories,
                    command.actor,
                    workspace_id=evaluation.workspace_id,
                    project_id=evaluation.project_id,
                    action=CLASSIFICATION_EXECUTE,
                    recorder=recorder,
                    occurred_at=now,
                )

            ruleset = await repositories.rulesets.get(evaluation.ruleset_id)
            if ruleset is None:
                raise NotFoundError("interpretation_ruleset", evaluation.ruleset_id)

            validated = validate_interpretation_payload(
                payload, evaluation=evaluation, ruleset=ruleset
            )

            if evaluation.state is ClassificationEvaluationState.COMPLETED:
                existing = (
                    await repositories.classification_evaluations.get_classification(
                        evaluation.classification_id
                    )
                    if evaluation.classification_id
                    else None
                )
                if existing is not None and existing.payload_digest == validated.payload_digest:
                    # Same payload, already stored. Idempotent replay.
                    criteria = await repositories.classification_evaluations.list_criterion_evaluations(
                        classification_evaluation_id=evaluation.id
                    )
                    return IngestionResult(
                        evaluation=evaluation,
                        classification=existing,
                        criteria=criteria,
                    )

            if validated.is_rejected or validated.classification is None:
                finding = validated.blocking_finding
                code = finding.code if finding else "classification_missing"
                message = (
                    finding.message
                    if finding
                    else "the payload contains no suggested classification"
                )
                failed = await repositories.classification_evaluations.save(
                    _fail(evaluation, at=now, code=code, message=message)
                )
                await recorder.audit(
                    action="classification_evaluation.rejected",
                    outcome=AuditOutcome.FAILURE,
                    occurred_at=now,
                    actor_user_id=command.actor.actor_id if command.actor else None,
                    resource_type="classification_evaluation",
                    resource_id=failed.id,
                    workspace_id=failed.workspace_id,
                    project_id=failed.project_id,
                    new_state=failed.state.value,
                    detail={
                        "failure_code": code,
                        "payload_digest": validated.payload_digest,
                        "finding_codes": [item.code for item in validated.findings],
                    },
                )
                await recorder.event(
                    event_type=EventType.CLASSIFICATION_EVALUATION_REJECTED,
                    aggregate_type="classification_evaluation",
                    aggregate_id=failed.id,
                    occurred_at=now,
                    workspace_id=failed.workspace_id,
                    payload={"failure_code": code, "message": message},
                )
                return IngestionResult(
                    evaluation=failed, findings=validated.findings
                )

            claim = validated.classification
            classification_id = new_id("acl")
            criteria: list[CriterionEvaluationRecord] = []
            for item in validated.criteria:
                definition = ruleset.criterion(item.criterion_key)
                criteria.append(
                    CriterionEvaluationRecord(
                        id=new_id("cre"),
                        variant_id=evaluation.variant_id,
                        ruleset_id=ruleset.id,
                        ruleset_version=ruleset.version,
                        criterion_key=item.criterion_key,
                        applied=item.applied,
                        strength=CriterionStrength(item.strength),
                        direction=CriterionDirection(item.direction)
                        if item.direction
                        else definition.direction,
                        origin=DataOrigin.MACHINE_GENERATED,
                        evaluated_at=payload.produced_at or now,
                        family=definition.family if definition else None,
                        classification_evaluation_id=evaluation.id,
                        rationale=item.rationale,
                        evaluation_method=item.method,
                        scientific_execution_id=evaluation.scientific_execution_id,
                        evidence_ids=tuple(item.evidence_ids),
                        details=dict(item.details),
                        created_at=now,
                    )
                )
            await repositories.classification_evaluations.add_criterion_evaluations(
                tuple(criteria)
            )

            previous = await repositories.classification_evaluations.current_classification(
                variant_id=evaluation.variant_id,
                ruleset_id=ruleset.id,
                condition_identifier=evaluation.condition_identifier,
            )
            classification = AutomatedClassificationRecord(
                id=classification_id,
                evaluation_id=evaluation.id,
                workspace_id=evaluation.workspace_id,
                variant_id=evaluation.variant_id,
                ruleset_id=ruleset.id,
                ruleset_key=ruleset.ruleset_key,
                ruleset_version=ruleset.version,
                classification=Classification(claim.classification),
                version_number=(previous.version_number + 1) if previous else 1,
                project_id=evaluation.project_id,
                combination_rule_key=claim.combination_rule_key,
                rationale=claim.rationale,
                condition_identifier=evaluation.condition_identifier,
                gene_symbol=evaluation.gene_symbol,
                applied_criterion_keys=tuple(
                    item.criterion_key for item in validated.criteria if item.applied
                ),
                criterion_evaluation_ids=tuple(item.id for item in criteria),
                evidence_ids=tuple(
                    dict.fromkeys(
                        evidence_id
                        for item in validated.criteria
                        for evidence_id in item.evidence_ids
                    )
                ),
                computation=dict(claim.computation),
                engine_resource_id=payload.engine_resource_id
                or evaluation.engine_resource_id,
                engine_version=payload.engine_version or evaluation.engine_version,
                environment_version=payload.environment_version
                or evaluation.environment_version,
                container_image_digest=payload.container_image_digest
                or evaluation.container_image_digest,
                node_identity=payload.node_identity or evaluation.node_identity,
                scientific_execution_id=payload.scientific_execution_id
                or evaluation.scientific_execution_id,
                contract_version=payload.contract_version,
                input_digest=evaluation.input_digest,
                configuration_digest=ruleset.configuration_digest,
                payload_digest=validated.payload_digest,
                provenance=dict(payload.metadata),
                supersedes_id=previous.id if previous else None,
                is_development_payload=payload.is_development_payload,
                produced_at=payload.produced_at or now,
                created_at=now,
            )
            stored_classification = (
                await repositories.classification_evaluations.add_classification(
                    classification
                )
            )
            if previous is not None:
                await repositories.classification_evaluations.mark_superseded(
                    classification_id=previous.id,
                    superseded_by_id=stored_classification.id,
                )
                await recorder.event(
                    event_type=EventType.AUTOMATED_CLASSIFICATION_SUPERSEDED,
                    aggregate_type="automated_classification",
                    aggregate_id=previous.id,
                    occurred_at=now,
                    workspace_id=previous.workspace_id,
                    payload={"superseded_by_id": stored_classification.id},
                )

            ingesting = evaluation.transition_to(
                ClassificationEvaluationState.INGESTING, at=now
            )
            completed = await repositories.classification_evaluations.save(
                replace(
                    ingesting.transition_to(
                        ClassificationEvaluationState.COMPLETED, at=now
                    ),
                    classification_id=stored_classification.id,
                    scientific_execution_id=stored_classification.scientific_execution_id,
                    engine_resource_id=stored_classification.engine_resource_id,
                    engine_version=stored_classification.engine_version,
                    environment_version=stored_classification.environment_version,
                    container_image_digest=stored_classification.container_image_digest,
                    node_identity=stored_classification.node_identity,
                )
            )

            await recorder.audit(
                action="automated_classification.recorded",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id if command.actor else None,
                resource_type="automated_classification",
                resource_id=stored_classification.id,
                workspace_id=stored_classification.workspace_id,
                project_id=stored_classification.project_id,
                new_state=stored_classification.classification.value,
                detail={
                    "evaluation_id": completed.id,
                    "ruleset_key": ruleset.ruleset_key,
                    "ruleset_version": ruleset.version,
                    "decision_role": stored_classification.decision_role.value,
                    "applied_criteria": list(
                        stored_classification.applied_criterion_keys
                    ),
                    "supersedes_id": stored_classification.supersedes_id,
                    "payload_digest": stored_classification.payload_digest,
                    "is_development_payload": stored_classification.is_development_payload,
                    "finding_codes": [item.code for item in validated.findings],
                },
            )
            await recorder.event(
                event_type=EventType.AUTOMATED_CLASSIFICATION_RECORDED,
                aggregate_type="automated_classification",
                aggregate_id=stored_classification.id,
                occurred_at=now,
                workspace_id=stored_classification.workspace_id,
                payload={
                    "classification": stored_classification.classification.value,
                    "decision_role": stored_classification.decision_role.value,
                    "variant_id": stored_classification.variant_id,
                    "ruleset_id": ruleset.id,
                },
            )
            await recorder.event(
                event_type=EventType.CLASSIFICATION_EVALUATION_COMPLETED,
                aggregate_type="classification_evaluation",
                aggregate_id=completed.id,
                occurred_at=now,
                workspace_id=completed.workspace_id,
                payload={"classification_id": stored_classification.id},
            )
            return IngestionResult(
                evaluation=completed,
                classification=stored_classification,
                criteria=tuple(criteria),
                findings=validated.findings,
            )


def _fail(
    evaluation: ClassificationEvaluationRecord, *, at: Any, code: str, message: str
) -> ClassificationEvaluationRecord:
    if evaluation.is_terminal:
        return replace(evaluation, failure_code=code, failure_message=message)
    return evaluation.transition_to(
        ClassificationEvaluationState.FAILED,
        at=at,
        failure_code=code,
        failure_message=message,
    )


__all__ = [
    "FAILURE_PAYLOAD_REJECTED",
    "IngestInterpretationCommand",
    "IngestInterpretationPayload",
    "IngestionResult",
]
