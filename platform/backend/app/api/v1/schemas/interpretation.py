"""Transport schemas for rulesets, automated evaluation and benchmark validation.

Conventions carried over from the other schema modules: request payloads forbid
unknown fields, responses expose enum *values*, and nothing internal is serialized
to a tenant client.

Three things specific to this surface:

* **A ruleset version is identity plus configuration digest.** A classification
  without them is not reproducible, so both always travel with the result.
* **An automated suggestion is labelled as one.** ``decision_role`` is always
  present and is never a human decision; a superseded suggestion stays visible.
* **Benchmarking never inflates its own claim.** A run reports the validation kind
  it can actually support, and an accuracy run must name its reference corpus.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel, Collection
from app.api.v1.schemas.tenancy import PageMeta

# --------------------------------------------------------------------------- #
# Ruleset definition                                                          #
# --------------------------------------------------------------------------- #


class CriterionDefinitionPayload(ApiModel):
    """One criterion a ruleset version declares."""

    criterion_key: str = Field(min_length=1, max_length=64)
    family: str = Field(description="pvs | ps | pm | pp | ba | bs | bp")
    direction: str = Field(description="pathogenic | benign")
    default_strength: str
    description: str | None = Field(default=None, max_length=2000)
    permitted_strengths: list[str] | None = Field(
        default=None,
        description="Strengths a specification may legitimately apply. Empty means "
        "the default strength only.",
    )
    evidence_categories: list[str] | None = None
    requires_evidence: bool = True
    display_order: int | None = None
    metadata: dict[str, object] | None = None


class CriterionDefinitionResponse(ApiModel):
    criterion_key: str
    family: str
    direction: str
    default_strength: str
    description: str | None
    permitted_strengths: list[str]
    evidence_categories: list[str]
    requires_evidence: bool
    display_order: int | None


class CombinationRulePayload(ApiModel):
    """One declared combination rule. Data, never executable logic."""

    rule_key: str = Field(min_length=1, max_length=128)
    classification: str
    description: str | None = Field(default=None, max_length=2000)
    requirements: dict[str, object] | None = None
    precedence: int | None = None


class CombinationRuleResponse(ApiModel):
    rule_key: str
    classification: str
    description: str | None
    requirements: dict[str, object]
    precedence: int | None


class RegisterRulesetPayload(ApiModel):
    ruleset_key: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    guideline_source: str = Field(min_length=1, max_length=255)
    criteria: list[CriterionDefinitionPayload] = Field(min_length=1)
    combination_rules: list[CombinationRulePayload] = Field(min_length=1)
    description: str | None = Field(default=None, max_length=4000)
    guideline_citation: str | None = Field(default=None, max_length=1000)
    publication_reference: str | None = Field(default=None, max_length=1000)
    publication_year: int | None = None
    specification_scope: str | None = Field(
        default=None, description="general | gene | gene_condition | laboratory"
    )
    gene_symbol: str | None = Field(default=None, max_length=64)
    condition_identifier: str | None = Field(default=None, max_length=255)
    condition_term: str | None = Field(default=None, max_length=255)
    combination_strategy: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    capability_id: str | None = Field(default=None, max_length=255)
    capability_version: str | None = Field(default=None, max_length=64)
    engine_resource_id: str | None = Field(default=None, max_length=64)
    genome_assembly: str | None = Field(default=None, max_length=32)
    provenance: dict[str, object] | None = None
    metadata: dict[str, object] | None = None


class TransitionRulesetPayload(ApiModel):
    state: str = Field(description="activated | deprecated | retired | invalidated")
    reason: str | None = Field(default=None, max_length=2000)


class RulesetResponse(ApiModel):
    id: str
    ruleset_key: str
    version: str
    display_name: str
    guideline_source: str
    state: str
    description: str | None
    guideline_citation: str | None
    publication_reference: str | None
    publication_year: int | None
    specification_scope: str
    gene_symbol: str | None
    condition_identifier: str | None
    condition_term: str | None
    combination_strategy: str
    effective_from: datetime | None
    effective_to: datetime | None
    capability_id: str | None
    capability_version: str | None
    engine_resource_id: str | None
    genome_assembly: str | None
    configuration_digest: str | None
    criteria: list[CriterionDefinitionResponse]
    combination_rules: list[CombinationRuleResponse]
    is_usable: bool
    activated_at: datetime | None
    deprecated_at: datetime | None
    retired_at: datetime | None
    invalidated_at: datetime | None
    invalidation_reason: str | None
    created_at: datetime | None


class RulesetCollection(Collection[RulesetResponse]):
    page: PageMeta


# --------------------------------------------------------------------------- #
# Evaluation                                                                  #
# --------------------------------------------------------------------------- #


class RequestEvaluationPayload(ApiModel):
    workspace_id: str
    variant_id: str
    ruleset_id: str
    project_id: str | None = None
    gene_symbol: str | None = Field(default=None, max_length=64)
    transcript_identifier: str | None = Field(default=None, max_length=128)
    condition_identifier: str | None = Field(default=None, max_length=255)
    condition_term: str | None = Field(default=None, max_length=255)
    inheritance: str | None = Field(default=None, max_length=64)
    evidence_ids: list[str] | None = Field(
        default=None,
        description="Evidence to submit. Omitted means every evidence record the "
        "caller may read for this variant.",
    )
    idempotency_key: str | None = Field(default=None, max_length=128)
    metadata: dict[str, object] | None = None


class CriterionEvaluationResponse(ApiModel):
    id: str
    criterion_key: str
    family: str | None
    applied: bool
    strength: str
    direction: str
    origin: str
    rationale: str | None
    evidence_ids: list[str]
    evaluation_method: str | None
    is_override: bool
    evaluated_at: datetime | None


class AutomatedClassificationResponse(ApiModel):
    id: str
    evaluation_id: str
    variant_id: str
    ruleset_id: str
    ruleset_key: str
    ruleset_version: str
    classification: str
    #: Always an automated suggestion. It is not a human or final decision.
    decision_role: str
    version_number: int
    combination_rule_key: str | None
    rationale: str | None
    applied_criterion_keys: list[str]
    evidence_ids: list[str]
    engine_version: str | None
    environment_version: str | None
    node_identity: str | None
    scientific_execution_id: str | None
    contract_version: str | None
    input_digest: str | None
    configuration_digest: str | None
    payload_digest: str | None
    supersedes_id: str | None
    superseded_by_id: str | None
    is_current: bool
    is_development_payload: bool
    produced_at: datetime | None
    created_at: datetime | None


class ClassificationEvaluationResponse(ApiModel):
    id: str
    workspace_id: str
    project_id: str | None
    variant_id: str
    ruleset_id: str
    ruleset_key: str
    ruleset_version: str
    state: str
    gene_symbol: str | None
    transcript_identifier: str | None
    condition_identifier: str | None
    condition_term: str | None
    inheritance: str | None
    genome_assembly: str | None
    evidence_ids: list[str]
    input_digest: str | None
    configuration_digest: str | None
    capability_id: str | None
    engine_version: str | None
    node_identity: str | None
    scientific_execution_id: str | None
    job_id: str | None
    classification_id: str | None
    failure_code: str | None
    failure_message: str | None
    requested_at: datetime | None
    submitted_at: datetime | None
    completed_at: datetime | None


class ClassificationEvaluationCollection(Collection[ClassificationEvaluationResponse]):
    page: PageMeta


class ClassificationEvaluationDetailResponse(ApiModel):
    evaluation: ClassificationEvaluationResponse
    classification: AutomatedClassificationResponse | None
    criteria: list[CriterionEvaluationResponse]


class ClassificationHistoryResponse(ApiModel):
    """Every automated suggestion for one variant, superseded ones included."""

    items: list[AutomatedClassificationResponse]


# --------------------------------------------------------------------------- #
# Ingestion                                                                   #
# --------------------------------------------------------------------------- #


class RulesetIdentityPayload(ApiModel):
    ruleset_key: str
    ruleset_version: str
    ruleset_id: str | None = None
    guideline_source: str | None = None
    specification_scope: str | None = None
    configuration_digest: str | None = None


class CriterionClaimPayload(ApiModel):
    criterion_key: str
    applied: bool
    strength: str
    direction: str | None = None
    outcome: str | None = None
    rationale: str | None = Field(default=None, max_length=4000)
    evidence_ids: list[str] | None = None
    method: str | None = Field(default=None, max_length=255)
    details: dict[str, object] | None = None


class ClassificationClaimPayload(ApiModel):
    classification: str
    combination_rule_key: str | None = None
    rationale: str | None = Field(default=None, max_length=4000)
    applied_criterion_keys: list[str] | None = None
    computation: dict[str, object] | None = None


class IngestInterpretationPayloadBody(ApiModel):
    """One rules-engine delivery. Structured claims only, never a command."""

    contract_version: str
    evaluation_id: str
    ruleset: RulesetIdentityPayload
    criteria: list[CriterionClaimPayload] = Field(default_factory=list)
    classification: ClassificationClaimPayload | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    scientific_execution_id: str | None = None
    genome_assembly: str | None = None
    parameters_digest: str | None = None
    produced_at: datetime | None = None
    metadata: dict[str, object] | None = None
    is_development_payload: bool = False


class InterpretationFindingResponse(ApiModel):
    code: str
    severity: str
    message: str
    criterion_key: str | None
    detail: dict[str, object]


class InterpretationIngestionResponse(ApiModel):
    evaluation: ClassificationEvaluationResponse
    classification: AutomatedClassificationResponse | None
    criteria: list[CriterionEvaluationResponse]
    findings: list[InterpretationFindingResponse]
    accepted: bool


# --------------------------------------------------------------------------- #
# Benchmarks                                                                  #
# --------------------------------------------------------------------------- #


class RegisterBenchmarkCasePayload(ApiModel):
    case_key: str = Field(min_length=1, max_length=128)
    validation_kind: str = Field(description="contract | scientific_accuracy")
    input_snapshot: dict[str, object]
    expected_criteria: dict[str, object] | None = None
    expected_classification: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    source_reference: str | None = Field(
        default=None,
        max_length=1000,
        description="Required for an accuracy case: where the expected outputs "
        "came from.",
    )


class BenchmarkCaseResponse(ApiModel):
    id: str
    ruleset_id: str
    case_key: str
    validation_kind: str
    expected_classification: str | None
    expected_criteria: dict[str, object]
    description: str | None
    source_reference: str | None
    is_active: bool
    created_at: datetime | None


class ObservedCaseOutcomePayload(ApiModel):
    case_key: str
    observed_classification: str | None = None
    observed_criteria: dict[str, object] | None = None
    not_evaluated: bool = False
    detail: str | None = Field(default=None, max_length=2000)


class RecordBenchmarkRunPayload(ApiModel):
    observations: list[ObservedCaseOutcomePayload] = Field(default_factory=list)


class BenchmarkComparisonResponse(ApiModel):
    case_id: str
    case_key: str
    outcome: str
    validation_kind: str
    expected_classification: str | None
    observed_classification: str | None
    criterion_differences: list[dict[str, object]]
    severity: str
    detail: str | None


class BenchmarkRunResponse(ApiModel):
    id: str
    ruleset_id: str
    ruleset_key: str
    ruleset_version: str
    validation_kind: str
    case_count: int
    matched_count: int
    mismatched_count: int
    not_evaluated_count: int
    #: True only when every executed case was an accuracy case with a declared
    #: reference corpus. Never inferred from a passing contract run.
    is_accuracy_run: bool
    comparisons: list[BenchmarkComparisonResponse]
    executed_at: datetime | None


class BenchmarkCaseCollection(ApiModel):
    items: list[BenchmarkCaseResponse]


class BenchmarkRunCollection(Collection[BenchmarkRunResponse]):
    page: PageMeta


__all__ = [
    "AutomatedClassificationResponse",
    "BenchmarkCaseCollection",
    "BenchmarkCaseResponse",
    "BenchmarkComparisonResponse",
    "BenchmarkRunCollection",
    "BenchmarkRunResponse",
    "ClassificationClaimPayload",
    "ClassificationEvaluationCollection",
    "ClassificationEvaluationDetailResponse",
    "ClassificationEvaluationResponse",
    "ClassificationHistoryResponse",
    "CombinationRulePayload",
    "CombinationRuleResponse",
    "CriterionClaimPayload",
    "CriterionDefinitionPayload",
    "CriterionDefinitionResponse",
    "CriterionEvaluationResponse",
    "IngestInterpretationPayloadBody",
    "InterpretationFindingResponse",
    "InterpretationIngestionResponse",
    "ObservedCaseOutcomePayload",
    "RecordBenchmarkRunPayload",
    "RegisterBenchmarkCasePayload",
    "RegisterRulesetPayload",
    "RequestEvaluationPayload",
    "RulesetCollection",
    "RulesetIdentityPayload",
    "RulesetResponse",
    "TransitionRulesetPayload",
]
