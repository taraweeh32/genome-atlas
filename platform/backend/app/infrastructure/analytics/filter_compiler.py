"""Compiling a validated filter expression into a parameterized predicate.

This is the only place in the platform where a filter becomes SQL, and it obeys
three rules without exception:

* **No request content becomes SQL text.** Every value travels as a bound
  parameter. Column names are looked up in the field dictionary by field id, so a
  caller can only ever name a field the platform published.
* **Nothing is repaired or reinterpreted.** The expression arriving here has
  already been validated and canonicalized; the compiler is a mechanical
  translation of it. If it cannot translate something it raises, rather than
  emitting an approximation that would silently change what the user asked.
* **Missing is not a value.** ``IS MISSING`` compiles to a null test and nothing
  else; a comparison never matches a null row by accident, and a null is never
  coerced to zero, false or the empty string. A filter that excludes rows because
  the data does not report the field excludes them for that reason alone.

Ranking never appears here. A filter decides membership; it never produces a
score, and no operator in this module can contribute to an ordering.
"""

from __future__ import annotations

import re

from app.application.ports import AnalyticalPredicate
from app.domain.errors import InfrastructureError
from app.domain.query.expressions import (
    CONDITION_KIND,
    FilterCondition,
    FilterGroup,
    FilterNode,
)
from app.domain.query.fields import FilterFieldDefinition, FilterFieldRegistry
from app.domain.query.operators import FilterOperator, LogicalOperator

#: Physical identifiers are platform-authored, but they are still checked here:
#: defence in depth costs one regex and removes a whole class of mistake.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

#: Operators that compare a column to exactly one bound value.
_BINARY_SQL: dict[FilterOperator, str] = {
    FilterOperator.EQUALS: "=",
    FilterOperator.NOT_EQUALS: "<>",
    FilterOperator.GREATER_THAN: ">",
    FilterOperator.GREATER_THAN_OR_EQUAL: ">=",
    FilterOperator.LESS_THAN: "<",
    FilterOperator.LESS_THAN_OR_EQUAL: "<=",
    FilterOperator.BEFORE: "<",
    FilterOperator.AFTER: ">",
    FilterOperator.ON: "=",
}

#: Operators that test a stored value's *shape* rather than compare it. Each keeps
#: "missing" and "present but empty/false" apart, which is the whole point of
#: having both: an empty string is a reported value, an absent one is not.
_SHAPE_SQL: dict[FilterOperator, str] = {
    FilterOperator.IS_EMPTY: "= ''",
    FilterOperator.IS_NOT_EMPTY: "<> ''",
    FilterOperator.IS_TRUE: "= TRUE",
    FilterOperator.IS_FALSE: "= FALSE",
}

#: Text matching. The pattern is assembled from a *bound* parameter, never from
#: interpolated text, so a user-supplied ``%`` matches literally where it should.
_TEXT_SQL: dict[FilterOperator, tuple[str, str]] = {
    FilterOperator.CONTAINS: ("LIKE", "%{}%"),
    FilterOperator.STARTS_WITH: ("LIKE", "{}%"),
    FilterOperator.ENDS_WITH: ("LIKE", "%{}"),
}


def quote_identifier(name: str) -> str:
    if not _IDENTIFIER.fullmatch(name):
        raise InfrastructureError("invalid analytical identifier")
    return f'"{name}"'


def _column(definition: FilterFieldDefinition) -> str:
    return quote_identifier(definition.column)


def _escape_for_like(value: str) -> str:
    """Escape LIKE metacharacters in a *bound* value.

    ``contains "50%"`` must look for a literal per-cent sign. The escaped string
    is still bound as a parameter; only its content changes.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _condition_sql(
    condition: FilterCondition, registry: FilterFieldRegistry
) -> AnalyticalPredicate:
    definition = registry.get(condition.field_id)
    if definition is None:
        raise InfrastructureError("unknown filter field in a validated expression")
    column = _column(definition)
    base = _operator_sql(condition, column)
    if not condition.negated:
        return base
    # Negation keeps the missing-value rule intact. Plain ``NOT (...)`` would let
    # every row that never reported the field satisfy the negated condition, which
    # would silently widen "value is not X" into "value is not X, or was never
    # reported at all" — two different facts.
    return AnalyticalPredicate(f"({column} IS NOT NULL AND NOT {base.sql})", base.parameters)


def _operator_sql(condition: FilterCondition, column: str) -> AnalyticalPredicate:
    operator = condition.operator
    values = tuple(condition.values)

    if operator is FilterOperator.IS_MISSING:
        return AnalyticalPredicate(f"({column} IS NULL)")
    if operator is FilterOperator.IS_PRESENT:
        return AnalyticalPredicate(f"({column} IS NOT NULL)")

    if operator in _SHAPE_SQL:
        return AnalyticalPredicate(
            f"({column} IS NOT NULL AND {column} {_SHAPE_SQL[operator]})"
        )

    if operator is FilterOperator.NOT_BETWEEN:
        if len(values) != 2:
            raise InfrastructureError("range operator without two bounds")
        return AnalyticalPredicate(
            f"({column} IS NOT NULL AND ({column} < ? OR {column} > ?))", values
        )

    if operator in (FilterOperator.BETWEEN, FilterOperator.WITHIN_RANGE):
        if len(values) != 2:
            raise InfrastructureError("range operator without two bounds")
        return AnalyticalPredicate(
            f"({column} IS NOT NULL AND {column} >= ? AND {column} <= ?)", values
        )

    if operator in (FilterOperator.IN, FilterOperator.NOT_IN):
        if not values:
            raise InfrastructureError("empty value list in a validated expression")
        placeholders = ", ".join("?" for _ in values)
        keyword = "IN" if operator is FilterOperator.IN else "NOT IN"
        return AnalyticalPredicate(
            f"({column} IS NOT NULL AND {column} {keyword} ({placeholders}))", values
        )

    if len(values) != 1:
        raise InfrastructureError("operator requires exactly one value")
    value = values[0]

    if operator in _TEXT_SQL:
        keyword, template = _TEXT_SQL[operator]
        pattern = template.format(_escape_for_like(str(value)))
        return AnalyticalPredicate(
            f"({column} IS NOT NULL AND {column} {keyword} ? ESCAPE '\\')", (pattern,)
        )

    if operator in _BINARY_SQL:
        # An explicit NOT NULL guard keeps three-valued logic from turning a
        # "does not equal" into "reported and does not equal" by accident: a row
        # that never reported the field is excluded because the data is missing,
        # which is what the validated semantics say.
        return AnalyticalPredicate(
            f"({column} IS NOT NULL AND {column} {_BINARY_SQL[operator]} ?)", (value,)
        )

    raise InfrastructureError("operator has no analytical compilation")


def _node_sql(node: FilterNode, registry: FilterFieldRegistry) -> AnalyticalPredicate:
    if node.kind == CONDITION_KIND:
        assert isinstance(node, FilterCondition)
        return _condition_sql(node, registry)

    assert isinstance(node, FilterGroup)
    if not node.children:
        raise InfrastructureError("empty group in a validated expression")

    compiled = [_node_sql(child, registry) for child in node.children]
    parameters: tuple[object, ...] = ()
    for part in compiled:
        parameters += part.parameters

    if node.operator is LogicalOperator.NOT:
        # NOT is applied to the group's single child exactly as written. The
        # expression is never rewritten by De Morgan, because a rewritten tree is
        # no longer the tree the user saved.
        return AnalyticalPredicate(f"(NOT {compiled[0].sql})", parameters)

    joiner = " AND " if node.operator is LogicalOperator.AND else " OR "
    return AnalyticalPredicate(
        "(" + joiner.join(part.sql for part in compiled) + ")", parameters
    )


def compile_filter(
    expression: FilterNode | None, registry: FilterFieldRegistry
) -> AnalyticalPredicate | None:
    """Compile a canonical expression, or ``None`` when there is no filter.

    An absent filter is deliberately not compiled to ``TRUE``: "no filter" and
    "a filter that keeps everything" are recorded differently in the execution
    record, and one is not silently rendered as the other.
    """
    if expression is None:
        return None
    return _node_sql(expression, registry)


__all__ = ["compile_filter", "quote_identifier"]
