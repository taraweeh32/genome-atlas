"""Filtering and ranking domain.

Two concepts live here and are deliberately kept apart:

* **Filtering** decides *which* variants satisfy a set of declared conditions.
* **Ranking** decides *in what order* the variants that survived filtering are
  presented.

Neither derives scientific content. Both consume fields that the scientific data
layer already recorded (Package 6), and every configuration they execute is
declarative, validated against a versioned field dictionary, canonicalized and
hashed so an execution can be reproduced exactly. No user input ever becomes
executable code or raw SQL: the analytical layer compiles a validated expression
into a parameterized query, and nothing else.
"""

from app.domain.query.canonical import canonical_hash, canonical_payload, canonicalize
from app.domain.query.entities import (
    FilterDefinitionRecord,
    FilterExecutionRecord,
    FilterPresetRecord,
    FilterPresetVersionRecord,
    FilterVersionRecord,
    RankingDefinitionRecord,
    RankingExecutionRecord,
    RankingPresetRecord,
    RankingPresetVersionRecord,
    RankingVersionRecord,
    SavedViewRecord,
)
from app.domain.query.expressions import (
    FilterCondition,
    FilterGroup,
    FilterNode,
    node_from_payload,
)
from app.domain.query.fields import (
    DEFAULT_FIELD_REGISTRY,
    FIELD_DICTIONARY_VERSION,
    FilterFieldDefinition,
    FilterFieldRegistry,
)
from app.domain.query.operators import (
    FilterDataType,
    FilterOperator,
    LogicalOperator,
    OperatorArity,
    operator_arity,
    operators_for,
)
from app.domain.query.ranking import (
    RANKING_METHOD_REGISTRY,
    RankingComponent,
    RankingComponentKind,
    RankingConfigurationSpec,
    RankingDirection,
    RankingMethodDefinition,
    RankingMissingBehaviour,
    RowScore,
    ValidatedRanking,
    prioritize_row,
    validate_ranking,
)
from app.domain.query.validation import (
    FilterLimits,
    FilterValidationIssue,
    ValidatedFilter,
    combine_expressions,
    validate_filter,
)

__all__ = [
    "DEFAULT_FIELD_REGISTRY",
    "FIELD_DICTIONARY_VERSION",
    "RANKING_METHOD_REGISTRY",
    "FilterCondition",
    "FilterDataType",
    "FilterDefinitionRecord",
    "FilterExecutionRecord",
    "FilterFieldDefinition",
    "FilterFieldRegistry",
    "FilterGroup",
    "FilterLimits",
    "FilterNode",
    "FilterOperator",
    "FilterPresetRecord",
    "FilterPresetVersionRecord",
    "FilterValidationIssue",
    "FilterVersionRecord",
    "LogicalOperator",
    "OperatorArity",
    "RankingComponent",
    "RankingComponentKind",
    "RankingConfigurationSpec",
    "RankingDefinitionRecord",
    "RankingDirection",
    "RankingExecutionRecord",
    "RankingMethodDefinition",
    "RankingMissingBehaviour",
    "RankingPresetRecord",
    "RankingPresetVersionRecord",
    "RankingVersionRecord",
    "RowScore",
    "SavedViewRecord",
    "ValidatedFilter",
    "ValidatedRanking",
    "canonical_hash",
    "canonical_payload",
    "canonicalize",
    "combine_expressions",
    "node_from_payload",
    "operator_arity",
    "operators_for",
    "prioritize_row",
    "validate_filter",
    "validate_ranking",
]
