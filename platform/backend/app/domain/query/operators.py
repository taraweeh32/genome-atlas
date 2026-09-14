"""Filter data types, logical connectives and type-aware operators.

Operators are a *closed vocabulary*. A client selects an operator by identifier;
it never supplies a comparison expression, a function name or a fragment of SQL.
Which operators a field admits follows from the field's declared data type (and
may be narrowed further by the field definition itself), so "contains" can never
be applied to a decimal and "between" can never be applied to a boolean.

Missing-value operators (``is_missing``/``is_present``) are first-class rather
than emergent. Absence in genomic data carries meaning — unreported is not zero
and not false — so asking for it is an explicit operator, and every ordinary
comparison leaves absent values out instead of coercing them.
"""

from __future__ import annotations

from app.domain.value_objects.enums import StrEnum


class FilterDataType(StrEnum):
    """The type of a filterable field, which decides its operator set."""

    STRING = "string"
    #: A bounded or enumerated set of labels. Filtered by identity, never by
    #: substring, and possibly high-cardinality (see the field definition).
    CATEGORICAL = "categorical"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    #: A coordinate on a contig. Compared numerically, always alongside the
    #: contig field: a bare position range is meaningless on its own.
    GENOMIC_POSITION = "genomic_position"
    #: An opaque identifier (variant id, sample key, accession). Compared by
    #: identity and prefix only.
    IDENTIFIER = "identifier"


class LogicalOperator(StrEnum):
    AND = "and"
    OR = "or"
    #: Negation of exactly one child, so no group can express an ambiguous
    #: "not (a, b)". Condition-level negation is the ``negated`` flag.
    NOT = "not"


class FilterOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    IN = "in"
    NOT_IN = "not_in"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    BETWEEN = "between"
    NOT_BETWEEN = "not_between"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    BEFORE = "before"
    AFTER = "after"
    ON = "on"
    #: Structured genomic range: two positions on the contig already constrained
    #: by a sibling contig condition.
    WITHIN_RANGE = "within_range"
    IS_MISSING = "is_missing"
    IS_PRESENT = "is_present"


class OperatorArity(StrEnum):
    """How many values an operator consumes. Checked before anything executes."""

    NONE = "none"
    ONE = "one"
    TWO = "two"
    MANY = "many"


_ARITY: dict[FilterOperator, OperatorArity] = {
    FilterOperator.EQUALS: OperatorArity.ONE,
    FilterOperator.NOT_EQUALS: OperatorArity.ONE,
    FilterOperator.CONTAINS: OperatorArity.ONE,
    FilterOperator.STARTS_WITH: OperatorArity.ONE,
    FilterOperator.ENDS_WITH: OperatorArity.ONE,
    FilterOperator.IN: OperatorArity.MANY,
    FilterOperator.NOT_IN: OperatorArity.MANY,
    FilterOperator.IS_EMPTY: OperatorArity.NONE,
    FilterOperator.IS_NOT_EMPTY: OperatorArity.NONE,
    FilterOperator.GREATER_THAN: OperatorArity.ONE,
    FilterOperator.GREATER_THAN_OR_EQUAL: OperatorArity.ONE,
    FilterOperator.LESS_THAN: OperatorArity.ONE,
    FilterOperator.LESS_THAN_OR_EQUAL: OperatorArity.ONE,
    FilterOperator.BETWEEN: OperatorArity.TWO,
    FilterOperator.NOT_BETWEEN: OperatorArity.TWO,
    FilterOperator.IS_TRUE: OperatorArity.NONE,
    FilterOperator.IS_FALSE: OperatorArity.NONE,
    FilterOperator.BEFORE: OperatorArity.ONE,
    FilterOperator.AFTER: OperatorArity.ONE,
    FilterOperator.ON: OperatorArity.ONE,
    FilterOperator.WITHIN_RANGE: OperatorArity.TWO,
    FilterOperator.IS_MISSING: OperatorArity.NONE,
    FilterOperator.IS_PRESENT: OperatorArity.NONE,
}

#: Operators every field admits, whatever its type: asking whether a value was
#: reported at all is meaningful for every field the platform stores.
PRESENCE_OPERATORS: frozenset[FilterOperator] = frozenset(
    {FilterOperator.IS_MISSING, FilterOperator.IS_PRESENT}
)

_STRING_OPERATORS = frozenset(
    {
        FilterOperator.EQUALS,
        FilterOperator.NOT_EQUALS,
        FilterOperator.CONTAINS,
        FilterOperator.STARTS_WITH,
        FilterOperator.ENDS_WITH,
        FilterOperator.IN,
        FilterOperator.NOT_IN,
        FilterOperator.IS_EMPTY,
        FilterOperator.IS_NOT_EMPTY,
    }
)
_CATEGORICAL_OPERATORS = frozenset(
    {
        FilterOperator.EQUALS,
        FilterOperator.NOT_EQUALS,
        FilterOperator.IN,
        FilterOperator.NOT_IN,
    }
)
_NUMERIC_OPERATORS = frozenset(
    {
        FilterOperator.EQUALS,
        FilterOperator.NOT_EQUALS,
        FilterOperator.GREATER_THAN,
        FilterOperator.GREATER_THAN_OR_EQUAL,
        FilterOperator.LESS_THAN,
        FilterOperator.LESS_THAN_OR_EQUAL,
        FilterOperator.BETWEEN,
        FilterOperator.NOT_BETWEEN,
        FilterOperator.IN,
        FilterOperator.NOT_IN,
    }
)
_BOOLEAN_OPERATORS = frozenset({FilterOperator.IS_TRUE, FilterOperator.IS_FALSE})
_DATETIME_OPERATORS = frozenset(
    {
        FilterOperator.BEFORE,
        FilterOperator.AFTER,
        FilterOperator.ON,
        FilterOperator.BETWEEN,
        FilterOperator.NOT_BETWEEN,
    }
)
_POSITION_OPERATORS = frozenset(
    {
        FilterOperator.EQUALS,
        FilterOperator.GREATER_THAN,
        FilterOperator.GREATER_THAN_OR_EQUAL,
        FilterOperator.LESS_THAN,
        FilterOperator.LESS_THAN_OR_EQUAL,
        FilterOperator.BETWEEN,
        FilterOperator.WITHIN_RANGE,
    }
)
_IDENTIFIER_OPERATORS = frozenset(
    {
        FilterOperator.EQUALS,
        FilterOperator.NOT_EQUALS,
        FilterOperator.IN,
        FilterOperator.NOT_IN,
        FilterOperator.STARTS_WITH,
    }
)

_BY_TYPE: dict[FilterDataType, frozenset[FilterOperator]] = {
    FilterDataType.STRING: _STRING_OPERATORS | PRESENCE_OPERATORS,
    FilterDataType.CATEGORICAL: _CATEGORICAL_OPERATORS | PRESENCE_OPERATORS,
    FilterDataType.INTEGER: _NUMERIC_OPERATORS | PRESENCE_OPERATORS,
    FilterDataType.DECIMAL: _NUMERIC_OPERATORS | PRESENCE_OPERATORS,
    FilterDataType.BOOLEAN: _BOOLEAN_OPERATORS | PRESENCE_OPERATORS,
    FilterDataType.DATETIME: _DATETIME_OPERATORS | PRESENCE_OPERATORS,
    FilterDataType.GENOMIC_POSITION: _POSITION_OPERATORS | PRESENCE_OPERATORS,
    FilterDataType.IDENTIFIER: _IDENTIFIER_OPERATORS | PRESENCE_OPERATORS,
}

#: Operators that compare against text rather than a whole value. Kept nameable
#: so the resource-governance limits can price them differently from equality.
TEXT_MATCH_OPERATORS: frozenset[FilterOperator] = frozenset(
    {FilterOperator.CONTAINS, FilterOperator.STARTS_WITH, FilterOperator.ENDS_WITH}
)

#: Operators that consume a list. Their length is bounded by configuration.
LIST_OPERATORS: frozenset[FilterOperator] = frozenset(
    {FilterOperator.IN, FilterOperator.NOT_IN}
)

NUMERIC_DATA_TYPES: frozenset[FilterDataType] = frozenset(
    {FilterDataType.INTEGER, FilterDataType.DECIMAL, FilterDataType.GENOMIC_POSITION}
)


def operator_arity(operator: FilterOperator) -> OperatorArity:
    return _ARITY[operator]


def operators_for(data_type: FilterDataType) -> frozenset[FilterOperator]:
    """Every operator the given data type admits."""
    return _BY_TYPE[data_type]


__all__ = [
    "LIST_OPERATORS",
    "NUMERIC_DATA_TYPES",
    "PRESENCE_OPERATORS",
    "TEXT_MATCH_OPERATORS",
    "FilterDataType",
    "FilterOperator",
    "LogicalOperator",
    "OperatorArity",
    "operator_arity",
    "operators_for",
]
