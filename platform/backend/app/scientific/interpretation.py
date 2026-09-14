"""SCIENTIFIC INTERPRETATION CONTRACT (application side only).

The versioned shape in which the **independently deployable ACMG/AMP rules
engine** receives a structured interpretation request and hands back structured
criterion evaluations and a suggested classification.

This module contains no rule logic. There is no criterion table here, no
combination arithmetic, no strength arithmetic, no point system, no Bayesian
posterior, no pathogenicity heuristic. It declares:

* what the application sends — a ruleset identity, the exact evidence it selected,
  the variant and its gene/disease context, and the reference context;
* what the engine may say back — per-criterion evaluations, each naming the
  evidence it rests on, plus one suggested classification naming the combination
  rule it came out of.

Rules the application enforces structurally when a payload arrives:

* **Ruleset identity is mandatory and must match the request.** An evaluation that
  names a different ruleset version than the one requested is refused, never
  reattributed.
* **A criterion must exist in that ruleset version, at a strength that version
  permits.** Unknown criteria and unpermitted strengths are rejected findings.
* **Every applied criterion names its evidence.** Evidence outside the selection
  the request carried is refused: an engine cannot introduce evidence the platform
  never authorized it to see.
* **A suggestion is a suggestion.** Whatever the engine returns is stored with
  ``ClassificationDecisionRole.AUTOMATED_SUGGESTION`` and can never become a
  reviewer decision, an adjudication or a finalized interpretation by itself.
* **Rows stay outside the request.** Only bounded inline batches are accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: Bumped whenever the shapes below change incompatibly. Persisted with every
#: stored evaluation so an old payload stays interpretable.
INTERPRETATION_CONTRACT_VERSION = "1"

#: One evaluation concerns one variant in one context, so this bound is generous.
#: It exists so a payload cannot become an unbounded upload.
MAX_INLINE_CRITERION_EVALUATIONS = 500

#: The capability the rules engine declares. Discovered, never assumed: a ruleset
#: version states the capability it needs, and submission fails if the configured
#: subsystem does not declare it.
DEFAULT_INTERPRETATION_CAPABILITY = "variant.interpret.acmg"


@dataclass(frozen=True, slots=True)
class RulesetIdentity:
    """The versioned ruleset an evaluation was produced under."""

    ruleset_key: str
    ruleset_version: str
    #: Platform identifier of the registered ruleset version, when the producer
    #: knows it. Resolution still happens server-side against the registry.
    ruleset_id: str | None = None
    guideline_source: str | None = None
    specification_scope: str | None = None
    configuration_digest: str | None = None

    @property
    def is_identified(self) -> bool:
        return bool(self.ruleset_key and self.ruleset_version)


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """One evidence record the application authorized the engine to consider.

    The engine receives identities and stated properties, never a licence to fetch
    anything itself: evidence retrieval is the evidence layer's responsibility.
    """

    evidence_id: str
    category: str
    direction: str
    strength: str
    applicability: str
    source_key: str | None = None
    source_version: str | None = None
    source_identifier: str | None = None
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class InterpretationRequestSpecification:
    """Everything the engine is told, as structured data.

    No command line, no script, no expression, no free-form parameter that could
    become code. This is the whole surface of what the application may ask for.
    """

    evaluation_id: str
    ruleset: RulesetIdentity
    variant_id: str
    variant_identifier: str | None = None
    genome_assembly: str | None = None
    reference_genome_resource_id: str | None = None
    gene_symbol: str | None = None
    transcript_identifier: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None
    inheritance: str | None = None
    evidence: tuple[EvidenceReference, ...] = ()
    #: Declared criteria and combination rules of the pinned ruleset version, sent
    #: so the engine evaluates exactly the version the platform recorded.
    criteria: tuple[dict[str, Any], ...] = ()
    combination_rules: tuple[dict[str, Any], ...] = ()
    combination_strategy: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    provenance_context: dict[str, Any] = field(default_factory=dict)

    def as_parameters(self) -> dict[str, Any]:
        """Serialize for ``ScientificExecutionRequest.parameters``."""
        return {
            "contract": "interpretation",
            "contract_version": INTERPRETATION_CONTRACT_VERSION,
            "evaluation_id": self.evaluation_id,
            "ruleset": {
                "ruleset_id": self.ruleset.ruleset_id,
                "ruleset_key": self.ruleset.ruleset_key,
                "ruleset_version": self.ruleset.ruleset_version,
                "guideline_source": self.ruleset.guideline_source,
                "specification_scope": self.ruleset.specification_scope,
                "configuration_digest": self.ruleset.configuration_digest,
                "combination_strategy": self.combination_strategy,
                "criteria": list(self.criteria),
                "combination_rules": list(self.combination_rules),
            },
            "subject": {
                "variant_id": self.variant_id,
                "variant_identifier": self.variant_identifier,
                "gene_symbol": self.gene_symbol,
                "transcript_identifier": self.transcript_identifier,
                "condition_identifier": self.condition_identifier,
                "condition_term": self.condition_term,
                "inheritance": self.inheritance,
            },
            "reference_context": {
                "genome_assembly": self.genome_assembly,
                "reference_genome_resource_id": self.reference_genome_resource_id,
            },
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "category": item.category,
                    "direction": item.direction,
                    "strength": item.strength,
                    "applicability": item.applicability,
                    "source_key": item.source_key,
                    "source_version": item.source_version,
                    "source_identifier": item.source_identifier,
                    "summary": item.summary,
                }
                for item in self.evidence
            ],
            "output_requirements": {
                "criterion_evaluations": True,
                "suggested_classification": True,
                "rationale": True,
            },
            "parameters": dict(self.parameters),
            "provenance_context": dict(self.provenance_context),
        }


@dataclass(frozen=True, slots=True)
class CriterionEvaluationClaim:
    """The engine's statement about one criterion of the pinned ruleset."""

    criterion_key: str
    applied: bool
    #: Stated, never derived from the criterion key: a specification may apply a
    #: criterion at a modified strength, and that is the whole point of storing it.
    strength: str
    direction: str | None = None
    outcome: str | None = None
    rationale: str | None = None
    #: Evidence the engine rested this criterion on. Must be a subset of what the
    #: request carried.
    evidence_ids: tuple[str, ...] = ()
    method: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClassificationClaim:
    """The engine's suggested classification. Never a decision."""

    classification: str
    #: The combination rule of the pinned ruleset that produced it, so the result
    #: is explainable against a stored, versioned rule rather than a black box.
    combination_rule_key: str | None = None
    rationale: str | None = None
    applied_criterion_keys: tuple[str, ...] = ()
    #: Strategy-specific working the engine chose to show (points, posterior,
    #: intermediate counts). Stored verbatim, never recomputed here.
    computation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InterpretationPayload:
    """The structured result of one interpretation execution."""

    contract_version: str
    #: The platform-side evaluation this payload answers.
    evaluation_id: str
    ruleset: RulesetIdentity
    criteria: tuple[CriterionEvaluationClaim, ...] = ()
    classification: ClassificationClaim | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    scientific_execution_id: str | None = None
    genome_assembly: str | None = None
    parameters_digest: str | None = None
    produced_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Set by development/mock adapters. Surfaced wherever the suggestion is shown
    #: so a stand-in evaluation can never be mistaken for a scientific one.
    is_development_payload: bool = False


__all__ = [
    "DEFAULT_INTERPRETATION_CAPABILITY",
    "INTERPRETATION_CONTRACT_VERSION",
    "MAX_INLINE_CRITERION_EVALUATIONS",
    "ClassificationClaim",
    "CriterionEvaluationClaim",
    "EvidenceReference",
    "InterpretationPayload",
    "InterpretationRequestSpecification",
    "RulesetIdentity",
]
