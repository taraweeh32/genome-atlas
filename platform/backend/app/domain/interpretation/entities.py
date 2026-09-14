"""Domain records for rulesets, automated evaluations and benchmark cases.

Versioning rule, stated once: a ruleset version is immutable. Its criteria and
combination rules are written when it is registered and never edited — a corrected
guideline, a modified criterion strength or a new gene/disease specification is a
*new* ruleset version. That is what keeps a historical classification explainable:
the rule text it was produced under still exists, unchanged, in the version it
named.

Automated classification results are versioned per ``(variant, ruleset, context)``.
Re-evaluating never overwrites: a new result supersedes the previous one, which
stays readable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.domain.errors import ConflictError, ValidationError
from app.domain.resource_lifecycle import (
    USABLE_RESOURCE_STATES,
    check_resource_transition,
)
from app.domain.value_objects.enums import (
    BenchmarkCaseOutcome,
    BenchmarkValidationKind,
    Classification,
    ClassificationDecisionRole,
    ClassificationEvaluationState,
    CriterionDirection,
    CriterionFamily,
    CriterionStrength,
    DataOrigin,
    RulesetCombinationStrategy,
    RulesetSpecificationScope,
    ScientificResourceState,
    ValidationSeverity,
)

#: Evaluation states from which nothing more happens.
TERMINAL_EVALUATION_STATES: frozenset[ClassificationEvaluationState] = frozenset(
    {
        ClassificationEvaluationState.COMPLETED,
        ClassificationEvaluationState.FAILED,
        ClassificationEvaluationState.CANCELLED,
    }
)

_EVALUATION_TRANSITIONS: dict[
    ClassificationEvaluationState, frozenset[ClassificationEvaluationState]
] = {
    ClassificationEvaluationState.REQUESTED: frozenset(
        {
            ClassificationEvaluationState.SUBMITTED,
            ClassificationEvaluationState.FAILED,
            ClassificationEvaluationState.CANCELLED,
        }
    ),
    ClassificationEvaluationState.SUBMITTED: frozenset(
        {
            ClassificationEvaluationState.RUNNING,
            ClassificationEvaluationState.INGESTING,
            ClassificationEvaluationState.FAILED,
            ClassificationEvaluationState.CANCELLED,
        }
    ),
    ClassificationEvaluationState.RUNNING: frozenset(
        {
            ClassificationEvaluationState.INGESTING,
            ClassificationEvaluationState.FAILED,
            ClassificationEvaluationState.CANCELLED,
        }
    ),
    ClassificationEvaluationState.INGESTING: frozenset(
        {
            ClassificationEvaluationState.COMPLETED,
            ClassificationEvaluationState.FAILED,
        }
    ),
    ClassificationEvaluationState.COMPLETED: frozenset(),
    ClassificationEvaluationState.FAILED: frozenset(),
    ClassificationEvaluationState.CANCELLED: frozenset(),
}


def configuration_digest(payload: dict[str, Any]) -> str:
    """Stable digest of a ruleset configuration or an evaluation input set.

    Two evaluations with the same digest were asked the same question; that is what
    makes reproducibility checkable rather than asserted.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CriterionDefinition:
    """One criterion a ruleset version declares.

    A criterion is defined independently of any variant and of any evidence. The
    family (PVS, PS, PM, PP, BA, BS, BP) and the *default* strength are separate
    facts, and the permitted strengths are declared explicitly — a specification
    that allows PM3 at supporting or strong strength says so here, rather than the
    platform inventing a rule about which modifications are allowed.
    """

    criterion_key: str
    family: CriterionFamily
    direction: CriterionDirection
    default_strength: CriterionStrength
    description: str | None = None
    #: Strengths this ruleset version permits for this criterion. Empty means the
    #: default strength only.
    permitted_strengths: tuple[CriterionStrength, ...] = ()
    #: Evidence categories the criterion is stated to draw on, for validation and
    #: for showing a reviewer why a criterion was even considered.
    evidence_categories: tuple[str, ...] = ()
    #: Whether an applied criterion must cite at least one evidence record.
    requires_evidence: bool = True
    display_order: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.criterion_key.strip():
            raise ValidationError(
                "a criterion requires a key", details={"field": "criterion_key"}
            )

    @property
    def allowed_strengths(self) -> tuple[CriterionStrength, ...]:
        return self.permitted_strengths or (self.default_strength,)

    def permits(self, strength: CriterionStrength) -> bool:
        return strength in self.allowed_strengths


@dataclass(frozen=True, slots=True)
class CombinationRule:
    """One declared way this ruleset version reaches a classification.

    The rule is *stored data*, not code: ``requirements`` holds the version's own
    stated conditions in structured form and the scientific component applies them.
    Nothing in the application evaluates this structure.
    """

    rule_key: str
    classification: Classification
    description: str | None = None
    requirements: dict[str, Any] = field(default_factory=dict)
    precedence: int | None = None

    def __post_init__(self) -> None:
        if not self.rule_key.strip():
            raise ValidationError(
                "a combination rule requires a key", details={"field": "rule_key"}
            )


@dataclass(frozen=True, slots=True)
class RulesetRecord:
    """One immutable, registered version of one interpretation ruleset.

    Identity is ``(ruleset_key, version)``. The guideline source and its citation
    are mandatory in substance: a ruleset with no stated source cannot be defended
    scientifically, so registration requires one.
    """

    id: str
    ruleset_key: str
    version: str
    display_name: str
    guideline_source: str
    state: ScientificResourceState = ScientificResourceState.REGISTERED
    description: str | None = None
    guideline_citation: str | None = None
    publication_reference: str | None = None
    publication_year: int | None = None
    specification_scope: RulesetSpecificationScope = RulesetSpecificationScope.GENERAL
    #: Gene/disease context for a specification-scoped version, e.g. a ClinGen
    #: VCEP specification. Null for a general framework version.
    gene_symbol: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None
    combination_strategy: RulesetCombinationStrategy = (
        RulesetCombinationStrategy.CRITERIA_COMBINATION
    )
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    #: The capability the scientific component must declare to evaluate it.
    capability_id: str | None = None
    capability_version: str | None = None
    engine_resource_id: str | None = None
    genome_assembly: str | None = None
    criteria: tuple[CriterionDefinition, ...] = ()
    combination_rules: tuple[CombinationRule, ...] = ()
    #: Digest over criteria + combination rules + strategy. Recorded on every
    #: evaluation, so a silently different configuration is detectable.
    configuration_digest: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_by: str | None = None
    activated_at: datetime | None = None
    deprecated_at: datetime | None = None
    retired_at: datetime | None = None
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None
    created_at: datetime | None = None
    record_version: int = 1

    def __post_init__(self) -> None:
        if not self.ruleset_key.strip():
            raise ValidationError(
                "a ruleset requires a key", details={"field": "ruleset_key"}
            )
        if not self.version.strip():
            raise ValidationError(
                "a ruleset requires a version", details={"field": "version"}
            )
        if not self.guideline_source.strip():
            raise ValidationError(
                "a ruleset requires a stated guideline source",
                details={"field": "guideline_source"},
            )

    @property
    def is_usable(self) -> bool:
        return self.state in USABLE_RESOURCE_STATES

    @property
    def criteria_by_key(self) -> dict[str, CriterionDefinition]:
        return {item.criterion_key: item for item in self.criteria}

    @property
    def declared_classifications(self) -> tuple[Classification, ...]:
        return tuple(
            dict.fromkeys(rule.classification for rule in self.combination_rules)
        )

    def criterion(self, criterion_key: str) -> CriterionDefinition | None:
        return self.criteria_by_key.get(criterion_key)

    def combination_rule(self, rule_key: str) -> CombinationRule | None:
        for rule in self.combination_rules:
            if rule.rule_key == rule_key:
                return rule
        return None

    def digest_payload(self) -> dict[str, Any]:
        return {
            "ruleset_key": self.ruleset_key,
            "version": self.version,
            "guideline_source": self.guideline_source,
            "specification_scope": self.specification_scope.value,
            "combination_strategy": self.combination_strategy.value,
            "criteria": [
                {
                    "criterion_key": item.criterion_key,
                    "family": item.family.value,
                    "direction": item.direction.value,
                    "default_strength": item.default_strength.value,
                    "permitted_strengths": [
                        strength.value for strength in item.allowed_strengths
                    ],
                    "requires_evidence": item.requires_evidence,
                    "evidence_categories": list(item.evidence_categories),
                }
                for item in self.criteria
            ],
            "combination_rules": [
                {
                    "rule_key": rule.rule_key,
                    "classification": rule.classification.value,
                    "requirements": rule.requirements,
                    "precedence": rule.precedence,
                }
                for rule in self.combination_rules
            ],
        }

    def with_digest(self) -> RulesetRecord:
        return replace(self, configuration_digest=configuration_digest(self.digest_payload()))

    def transition_to(
        self, state: ScientificResourceState, *, at: datetime, reason: str | None = None
    ) -> RulesetRecord:
        if state is self.state:
            return self
        check_resource_transition(
            current=self.state, target=state, resource_kind="ruleset"
        )
        stamps: dict[str, Any] = {}
        if state is ScientificResourceState.ACTIVE:
            stamps["activated_at"] = at
        elif state is ScientificResourceState.DEPRECATED:
            stamps["deprecated_at"] = at
        elif state is ScientificResourceState.RETIRED:
            stamps["retired_at"] = at
        elif state is ScientificResourceState.INVALIDATED:
            stamps["invalidated_at"] = at
            stamps["invalidation_reason"] = reason
        return replace(self, state=state, **stamps)


@dataclass(frozen=True, slots=True)
class ClassificationEvaluationRecord:
    """One requested automated evaluation of one variant under one ruleset version.

    The evaluation freezes what it asked: the ruleset version, the exact evidence
    identifiers selected, and a digest over both. Changing the evidence afterwards
    cannot change what this evaluation claims to have considered.
    """

    id: str
    workspace_id: str
    variant_id: str
    ruleset_id: str
    ruleset_key: str
    ruleset_version: str
    state: ClassificationEvaluationState = ClassificationEvaluationState.REQUESTED
    project_id: str | None = None
    gene_symbol: str | None = None
    transcript_identifier: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None
    inheritance: str | None = None
    genome_assembly: str | None = None
    reference_genome_resource_id: str | None = None
    #: The exact evidence records handed to the engine.
    evidence_ids: tuple[str, ...] = ()
    #: Digest over ruleset configuration + evidence selection + context.
    input_digest: str | None = None
    configuration_digest: str | None = None
    capability_id: str | None = None
    capability_version: str | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    scientific_execution_id: str | None = None
    job_id: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    requested_by: str | None = None
    requested_at: datetime | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    classification_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    #: Set when a benchmark run, not a user, requested this evaluation.
    benchmark_case_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    record_version: int = 1

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_EVALUATION_STATES

    def transition_to(
        self,
        state: ClassificationEvaluationState,
        *,
        at: datetime,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> ClassificationEvaluationRecord:
        if state is self.state:
            return self
        if state not in _EVALUATION_TRANSITIONS[self.state]:
            raise ConflictError(
                "this evaluation cannot move to that state",
                details={"from": self.state.value, "to": state.value},
            )
        stamps: dict[str, Any] = {}
        if state is ClassificationEvaluationState.SUBMITTED:
            stamps["submitted_at"] = at
        if state in TERMINAL_EVALUATION_STATES:
            stamps["completed_at"] = at
        if state is ClassificationEvaluationState.FAILED:
            stamps["failure_code"] = failure_code
            stamps["failure_message"] = failure_message
        return replace(self, state=state, **stamps)


@dataclass(frozen=True, slots=True)
class CriterionEvaluationRecord:
    """One criterion evaluation, automated or human.

    ``origin`` is what keeps the two apart forever: a machine-generated evaluation
    and a human evaluation are stored in the same shape but are never the same
    fact, and a human evaluation that replaces a suggestion points back at it.
    """

    id: str
    variant_id: str
    ruleset_id: str
    ruleset_version: str
    criterion_key: str
    applied: bool
    strength: CriterionStrength
    direction: CriterionDirection
    origin: DataOrigin
    evaluated_at: datetime
    family: CriterionFamily | None = None
    classification_evaluation_id: str | None = None
    interpretation_id: str | None = None
    interpretation_version_id: str | None = None
    rationale: str | None = None
    evaluated_by_user_id: str | None = None
    evaluation_method: str | None = None
    scientific_execution_id: str | None = None
    #: Evidence this criterion rests on. Stored as links, so the evidence layer
    #: stays the single owner of evidence content.
    evidence_ids: tuple[str, ...] = ()
    supersedes_evaluation_id: str | None = None
    is_override: bool = False
    override_reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    @property
    def is_automated(self) -> bool:
        return self.origin in {DataOrigin.MACHINE_GENERATED, DataOrigin.GENERATED}


@dataclass(frozen=True, slots=True)
class AutomatedClassificationRecord:
    """One suggested classification produced by the rules engine.

    ``decision_role`` is fixed to ``AUTOMATED_SUGGESTION``: this record is an input
    to human interpretation, never its outcome. Nothing in this layer can promote
    it, and the human review layer records its own decision separately.
    """

    id: str
    evaluation_id: str
    workspace_id: str
    variant_id: str
    ruleset_id: str
    ruleset_key: str
    ruleset_version: str
    classification: Classification
    version_number: int = 1
    project_id: str | None = None
    decision_role: ClassificationDecisionRole = (
        ClassificationDecisionRole.AUTOMATED_SUGGESTION
    )
    combination_rule_key: str | None = None
    rationale: str | None = None
    condition_identifier: str | None = None
    gene_symbol: str | None = None
    applied_criterion_keys: tuple[str, ...] = ()
    criterion_evaluation_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    computation: dict[str, Any] = field(default_factory=dict)
    engine_resource_id: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    scientific_execution_id: str | None = None
    contract_version: str | None = None
    input_digest: str | None = None
    configuration_digest: str | None = None
    payload_digest: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    is_development_payload: bool = False
    produced_at: datetime | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.decision_role is not ClassificationDecisionRole.AUTOMATED_SUGGESTION:
            # Structural guard: this table holds suggestions only. A reviewer's or
            # adjudicator's decision belongs to the interpretation layer.
            raise ValidationError(
                "an automated classification is always a suggestion",
                details={"field": "decision_role"},
            )

    @property
    def is_current(self) -> bool:
        return self.superseded_by_id is None


@dataclass(frozen=True, slots=True)
class BenchmarkCaseRecord:
    """One controlled case used to validate a ruleset version's engine behaviour.

    ``validation_kind`` is the honesty guard. A case is only
    ``SCIENTIFIC_ACCURACY`` when its expected outputs come from a declared external
    reference corpus, named in ``source_reference``. Everything else validates
    determinism and contract shape, and is reported as such — the platform never
    turns a structural check into an accuracy claim.
    """

    id: str
    ruleset_id: str
    case_key: str
    validation_kind: BenchmarkValidationKind
    #: The fixture input: variant identity, context and evidence claims. Data, not
    #: a computation, and never treated as real patient content.
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    expected_criteria: dict[str, Any] = field(default_factory=dict)
    expected_classification: Classification | None = None
    description: str | None = None
    #: Where the expected outputs came from. Required for accuracy cases.
    source_reference: str | None = None
    is_active: bool = True
    created_by: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            self.validation_kind is BenchmarkValidationKind.SCIENTIFIC_ACCURACY
            and not (self.source_reference or "").strip()
        ):
            raise ValidationError(
                "an accuracy benchmark case must name the reference corpus its "
                "expected outputs came from",
                details={"field": "source_reference"},
            )


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    """The outcome of comparing one case's expectation to what the engine returned.

    Comparison is verification, not computation: it reports equality of stored
    values and never adjusts, scores or interprets them.
    """

    case_id: str
    case_key: str
    outcome: BenchmarkCaseOutcome
    validation_kind: BenchmarkValidationKind
    expected_classification: str | None = None
    observed_classification: str | None = None
    criterion_differences: tuple[dict[str, Any], ...] = ()
    severity: ValidationSeverity = ValidationSeverity.INFO
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkRunRecord:
    """One execution of a ruleset version's benchmark cases."""

    id: str
    ruleset_id: str
    ruleset_key: str
    ruleset_version: str
    validation_kind: BenchmarkValidationKind
    case_count: int = 0
    matched_count: int = 0
    mismatched_count: int = 0
    not_evaluated_count: int = 0
    comparisons: tuple[BenchmarkComparison, ...] = ()
    #: True only when every executed case was an accuracy case with a declared
    #: reference corpus. Anything else is reported as contract validation.
    is_accuracy_run: bool = False
    executed_by: str | None = None
    executed_at: datetime | None = None
    created_at: datetime | None = None


__all__ = [
    "TERMINAL_EVALUATION_STATES",
    "AutomatedClassificationRecord",
    "BenchmarkCaseRecord",
    "BenchmarkComparison",
    "BenchmarkRunRecord",
    "ClassificationEvaluationRecord",
    "CombinationRule",
    "CriterionDefinition",
    "CriterionEvaluationRecord",
    "RulesetRecord",
    "configuration_digest",
]
