"""The interpretation ruleset layer: rulesets, criteria and automated evaluation.

What this package is, and what it deliberately is not.

**It is** the application's record of *which versioned rulesets exist*, *which
criteria and combination rules each version declares*, *which automated
evaluations were requested*, and *what the scientific interpretation component
answered*. Every stored result names the exact ruleset version, the exact
criterion evaluations and the exact evidence it rested on, so a historical
classification stays reproducible after the ruleset moves on.

**It is not** a rules engine. No criterion is decided here, no strength is
combined here, no classification is computed here. The rules engine is an
independently deployable scientific component reached only through the existing
scientific gateway, using the structured contract in
``app.scientific.interpretation``.

**And an automated result is not a decision.** Everything this package writes
carries ``ClassificationDecisionRole.AUTOMATED_SUGGESTION``. Reviewer decisions,
adjudication and finalized interpretations are separate states, owned by the human
review layer, and no code path here can produce one.
"""

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
    configuration_digest,
)
from app.domain.interpretation.validation import (
    ValidatedInterpretation,
    validate_interpretation_payload,
)

__all__ = [
    "AutomatedClassificationRecord",
    "BenchmarkCaseRecord",
    "BenchmarkComparison",
    "BenchmarkRunRecord",
    "ClassificationEvaluationRecord",
    "CombinationRule",
    "CriterionDefinition",
    "CriterionEvaluationRecord",
    "RulesetRecord",
    "ValidatedInterpretation",
    "configuration_digest",
    "validate_interpretation_payload",
]
