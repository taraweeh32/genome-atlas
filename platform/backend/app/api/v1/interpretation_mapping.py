"""Mapping between the interpretation layer and its transport schemas.

One-directional and explicit, like the other mapping modules: every field a client
sees is named here.

The judgements encoded here: a ruleset version always travels with its
configuration digest, an automated classification always declares its decision role
and whether it has been superseded, and a benchmark run reports the validation kind
it can actually support rather than the one a caller would prefer.
"""

from __future__ import annotations

from typing import Any

from app.api.v1.mapping import parse_enum
from app.api.v1.schemas.interpretation import (
    AutomatedClassificationResponse,
    BenchmarkCaseResponse,
    BenchmarkComparisonResponse,
    BenchmarkRunResponse,
    ClassificationEvaluationResponse,
    CombinationRulePayload,
    CombinationRuleResponse,
    CriterionDefinitionPayload,
    CriterionDefinitionResponse,
    CriterionEvaluationResponse,
    IngestInterpretationPayloadBody,
    InterpretationFindingResponse,
    ObservedCaseOutcomePayload,
    RegisterBenchmarkCasePayload,
    RulesetResponse,
)
from app.application.use_cases.interpretation.benchmarks import ObservedCaseOutcome
from app.domain.interpretation.entities import (
    AutomatedClassificationRecord,
    BenchmarkCaseRecord,
    BenchmarkComparison,
    BenchmarkRunRecord,
    ClassificationEvaluationRecord,
    CombinationRule,
    CriterionDefinition,
    CriterionEvaluationRecord,
    RulesetRecord,
)
from app.domain.interpretation.validation import InterpretationFinding
from app.domain.value_objects.enums import (
    BenchmarkValidationKind,
    Classification,
    CriterionDirection,
    CriterionFamily,
    CriterionStrength,
)
from app.scientific.interpretation import (
    ClassificationClaim,
    CriterionEvaluationClaim,
    InterpretationPayload,
    RulesetIdentity,
)


def _plain(value: dict[str, Any] | None) -> dict[str, object]:
    return dict(value or {})


# --------------------------------------------------------------------------- #
# Ruleset definition                                                          #
# --------------------------------------------------------------------------- #


def criterion_from_payload(payload: CriterionDefinitionPayload) -> CriterionDefinition:
    return CriterionDefinition(
        criterion_key=payload.criterion_key,
        family=parse_enum(CriterionFamily, payload.family, field="family"),
        direction=parse_enum(CriterionDirection, payload.direction, field="direction"),
        default_strength=parse_enum(
            CriterionStrength, payload.default_strength, field="default_strength"
        ),
        description=payload.description,
        permitted_strengths=tuple(
            parse_enum(CriterionStrength, item, field="permitted_strengths")
            for item in payload.permitted_strengths or ()
        ),
        evidence_categories=tuple(payload.evidence_categories or ()),
        requires_evidence=payload.requires_evidence,
        display_order=payload.display_order,
        metadata=_plain(payload.metadata),
    )


def combination_rule_from_payload(payload: CombinationRulePayload) -> CombinationRule:
    return CombinationRule(
        rule_key=payload.rule_key,
        classification=parse_enum(
            Classification, payload.classification, field="classification"
        ),
        description=payload.description,
        requirements=_plain(payload.requirements),
        precedence=payload.precedence,
    )


def criterion_definition_response(
    record: CriterionDefinition,
) -> CriterionDefinitionResponse:
    return CriterionDefinitionResponse(
        criterion_key=record.criterion_key,
        family=record.family.value,
        direction=record.direction.value,
        default_strength=record.default_strength.value,
        description=record.description,
        permitted_strengths=[item.value for item in record.permitted_strengths],
        evidence_categories=list(record.evidence_categories),
        requires_evidence=record.requires_evidence,
        display_order=record.display_order,
    )


def combination_rule_response(record: CombinationRule) -> CombinationRuleResponse:
    return CombinationRuleResponse(
        rule_key=record.rule_key,
        classification=record.classification.value,
        description=record.description,
        requirements=_plain(record.requirements),
        precedence=record.precedence,
    )


def ruleset_response(record: RulesetRecord) -> RulesetResponse:
    return RulesetResponse(
        id=record.id,
        ruleset_key=record.ruleset_key,
        version=record.version,
        display_name=record.display_name,
        guideline_source=record.guideline_source,
        state=record.state.value,
        description=record.description,
        guideline_citation=record.guideline_citation,
        publication_reference=record.publication_reference,
        publication_year=record.publication_year,
        specification_scope=record.specification_scope.value,
        gene_symbol=record.gene_symbol,
        condition_identifier=record.condition_identifier,
        condition_term=record.condition_term,
        combination_strategy=record.combination_strategy.value,
        effective_from=record.effective_from,
        effective_to=record.effective_to,
        capability_id=record.capability_id,
        capability_version=record.capability_version,
        engine_resource_id=record.engine_resource_id,
        genome_assembly=record.genome_assembly,
        configuration_digest=record.configuration_digest,
        criteria=[criterion_definition_response(item) for item in record.criteria],
        combination_rules=[
            combination_rule_response(item) for item in record.combination_rules
        ],
        is_usable=record.is_usable,
        activated_at=record.activated_at,
        deprecated_at=record.deprecated_at,
        retired_at=record.retired_at,
        invalidated_at=record.invalidated_at,
        invalidation_reason=record.invalidation_reason,
        created_at=record.created_at,
    )


# --------------------------------------------------------------------------- #
# Evaluation                                                                  #
# --------------------------------------------------------------------------- #


def evaluation_response(
    record: ClassificationEvaluationRecord,
) -> ClassificationEvaluationResponse:
    return ClassificationEvaluationResponse(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        variant_id=record.variant_id,
        ruleset_id=record.ruleset_id,
        ruleset_key=record.ruleset_key,
        ruleset_version=record.ruleset_version,
        state=record.state.value,
        gene_symbol=record.gene_symbol,
        transcript_identifier=record.transcript_identifier,
        condition_identifier=record.condition_identifier,
        condition_term=record.condition_term,
        inheritance=record.inheritance,
        genome_assembly=record.genome_assembly,
        evidence_ids=list(record.evidence_ids),
        input_digest=record.input_digest,
        configuration_digest=record.configuration_digest,
        capability_id=record.capability_id,
        engine_version=record.engine_version,
        node_identity=record.node_identity,
        scientific_execution_id=record.scientific_execution_id,
        job_id=record.job_id,
        classification_id=record.classification_id,
        failure_code=record.failure_code,
        failure_message=record.failure_message,
        requested_at=record.requested_at,
        submitted_at=record.submitted_at,
        completed_at=record.completed_at,
    )


def criterion_evaluation_response(
    record: CriterionEvaluationRecord,
) -> CriterionEvaluationResponse:
    return CriterionEvaluationResponse(
        id=record.id,
        criterion_key=record.criterion_key,
        family=record.family.value if record.family else None,
        applied=record.applied,
        strength=record.strength.value,
        direction=record.direction.value,
        origin=record.origin.value,
        rationale=record.rationale,
        evidence_ids=list(record.evidence_ids),
        evaluation_method=record.evaluation_method,
        is_override=record.is_override,
        evaluated_at=record.evaluated_at,
    )


def classification_response(
    record: AutomatedClassificationRecord,
) -> AutomatedClassificationResponse:
    return AutomatedClassificationResponse(
        id=record.id,
        evaluation_id=record.evaluation_id,
        variant_id=record.variant_id,
        ruleset_id=record.ruleset_id,
        ruleset_key=record.ruleset_key,
        ruleset_version=record.ruleset_version,
        classification=record.classification.value,
        decision_role=record.decision_role.value,
        version_number=record.version_number,
        combination_rule_key=record.combination_rule_key,
        rationale=record.rationale,
        applied_criterion_keys=list(record.applied_criterion_keys),
        evidence_ids=list(record.evidence_ids),
        engine_version=record.engine_version,
        environment_version=record.environment_version,
        node_identity=record.node_identity,
        scientific_execution_id=record.scientific_execution_id,
        contract_version=record.contract_version,
        input_digest=record.input_digest,
        configuration_digest=record.configuration_digest,
        payload_digest=record.payload_digest,
        supersedes_id=record.supersedes_id,
        superseded_by_id=record.superseded_by_id,
        is_current=record.is_current,
        is_development_payload=record.is_development_payload,
        produced_at=record.produced_at,
        created_at=record.created_at,
    )


def finding_response(record: InterpretationFinding) -> InterpretationFindingResponse:
    return InterpretationFindingResponse(
        code=record.code,
        severity=record.severity.value,
        message=record.message,
        criterion_key=getattr(record, "criterion_key", None),
        detail=_plain(getattr(record, "detail", None)),
    )


# --------------------------------------------------------------------------- #
# Ingestion                                                                   #
# --------------------------------------------------------------------------- #


def ingestion_payload(body: IngestInterpretationPayloadBody) -> InterpretationPayload:
    return InterpretationPayload(
        contract_version=body.contract_version,
        evaluation_id=body.evaluation_id,
        ruleset=RulesetIdentity(
            ruleset_key=body.ruleset.ruleset_key,
            ruleset_version=body.ruleset.ruleset_version,
            ruleset_id=body.ruleset.ruleset_id,
            guideline_source=body.ruleset.guideline_source,
            specification_scope=body.ruleset.specification_scope,
            configuration_digest=body.ruleset.configuration_digest,
        ),
        criteria=tuple(
            CriterionEvaluationClaim(
                criterion_key=item.criterion_key,
                applied=item.applied,
                strength=item.strength,
                direction=item.direction,
                outcome=item.outcome,
                rationale=item.rationale,
                evidence_ids=tuple(item.evidence_ids or ()),
                method=item.method,
                details=_plain(item.details),
            )
            for item in body.criteria
        ),
        classification=ClassificationClaim(
            classification=body.classification.classification,
            combination_rule_key=body.classification.combination_rule_key,
            rationale=body.classification.rationale,
            applied_criterion_keys=tuple(
                body.classification.applied_criterion_keys or ()
            ),
            computation=_plain(body.classification.computation),
        )
        if body.classification
        else None,
        engine_resource_id=body.engine_resource_id,
        engine_version=body.engine_version,
        environment_version=body.environment_version,
        container_image_digest=body.container_image_digest,
        node_identity=body.node_identity,
        scientific_execution_id=body.scientific_execution_id,
        genome_assembly=body.genome_assembly,
        parameters_digest=body.parameters_digest,
        produced_at=body.produced_at,
        metadata=_plain(body.metadata),
        is_development_payload=body.is_development_payload,
    )


# --------------------------------------------------------------------------- #
# Benchmarks                                                                  #
# --------------------------------------------------------------------------- #


def benchmark_case_response(record: BenchmarkCaseRecord) -> BenchmarkCaseResponse:
    return BenchmarkCaseResponse(
        id=record.id,
        ruleset_id=record.ruleset_id,
        case_key=record.case_key,
        validation_kind=record.validation_kind.value,
        expected_classification=record.expected_classification.value
        if record.expected_classification
        else None,
        expected_criteria=_plain(record.expected_criteria),
        description=record.description,
        source_reference=record.source_reference,
        is_active=record.is_active,
        created_at=record.created_at,
    )


def comparison_response(record: BenchmarkComparison) -> BenchmarkComparisonResponse:
    return BenchmarkComparisonResponse(
        case_id=record.case_id,
        case_key=record.case_key,
        outcome=record.outcome.value,
        validation_kind=record.validation_kind.value,
        expected_classification=record.expected_classification,
        observed_classification=record.observed_classification,
        criterion_differences=[_plain(item) for item in record.criterion_differences],
        severity=record.severity.value,
        detail=record.detail,
    )


def benchmark_run_response(record: BenchmarkRunRecord) -> BenchmarkRunResponse:
    return BenchmarkRunResponse(
        id=record.id,
        ruleset_id=record.ruleset_id,
        ruleset_key=record.ruleset_key,
        ruleset_version=record.ruleset_version,
        validation_kind=record.validation_kind.value,
        case_count=record.case_count,
        matched_count=record.matched_count,
        mismatched_count=record.mismatched_count,
        not_evaluated_count=record.not_evaluated_count,
        is_accuracy_run=record.is_accuracy_run,
        comparisons=[comparison_response(item) for item in record.comparisons],
        executed_at=record.executed_at,
    )


def benchmark_case_input(payload: RegisterBenchmarkCasePayload) -> dict[str, Any]:
    return {
        "case_key": payload.case_key,
        "validation_kind": parse_enum(
            BenchmarkValidationKind, payload.validation_kind, field="validation_kind"
        ),
        "input_snapshot": _plain(payload.input_snapshot),
        "expected_criteria": _plain(payload.expected_criteria),
        "expected_classification": parse_enum(
            Classification,
            payload.expected_classification,
            field="expected_classification",
        )
        if payload.expected_classification
        else None,
        "description": payload.description,
        "source_reference": payload.source_reference,
    }


def observation_input(payload: ObservedCaseOutcomePayload) -> ObservedCaseOutcome:
    return ObservedCaseOutcome(
        case_key=payload.case_key,
        observed_classification=payload.observed_classification,
        observed_criteria=_plain(payload.observed_criteria),
        not_evaluated=payload.not_evaluated,
        detail=payload.detail,
    )


__all__ = [
    "benchmark_case_input",
    "benchmark_case_response",
    "benchmark_run_response",
    "classification_response",
    "combination_rule_from_payload",
    "criterion_evaluation_response",
    "criterion_from_payload",
    "evaluation_response",
    "finding_response",
    "ingestion_payload",
    "observation_input",
    "ruleset_response",
]
