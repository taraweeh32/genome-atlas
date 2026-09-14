"""Filter validation and the shape a validated filter takes.

Validation is the boundary between "a client sent something" and "the platform
will execute this". It resolves every field against the dictionary, checks that
the operator is one the field's type admits, checks arity, coerces values to the
declared type, enforces configuration-driven safety limits, and reports *all*
findings with a path into the expression tree.

Nothing is repaired. A numeric field compared against ``"maybe"`` is an error, not
an opportunity to guess; a field the selected surface does not carry is an error,
not a condition to drop. Dropping a scientific condition silently would widen the
result set a clinician is looking at, which is the most dangerous thing this
module could do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.errors import ValidationError
from app.domain.query.canonical import (
    canonical_hash,
    canonical_json,
    canonical_payload,
    canonicalize,
)
from app.domain.query.expressions import (
    FilterCondition,
    FilterGroup,
    FilterNode,
    iter_conditions,
    node_count,
    node_depth,
)
from app.domain.query.fields import (
    FilterFieldDefinition,
    FilterFieldRegistry,
)
from app.domain.query.operators import (
    LIST_OPERATORS,
    NUMERIC_DATA_TYPES,
    PRESENCE_OPERATORS,
    TEXT_MATCH_OPERATORS,
    FilterDataType,
    FilterOperator,
    LogicalOperator,
    OperatorArity,
    operator_arity,
)


@dataclass(frozen=True, slots=True)
class FilterLimits:
    """Resource-governance limits. Supplied by configuration, never invented here."""

    max_depth: int = 8
    max_conditions: int = 100
    max_values_per_condition: int = 500
    max_expression_bytes: int = 65_536
    max_text_match_conditions: int = 10
    max_value_length: int = 512


@dataclass(frozen=True, slots=True)
class FilterValidationIssue:
    """One finding, addressed to the exact node that caused it."""

    path: str
    code: str
    message: str
    field_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "code": self.code,
            "message": self.message,
        }
        if self.field_id is not None:
            payload["field_id"] = self.field_id
        if self.detail:
            payload["detail"] = dict(self.detail)
        return payload


@dataclass(frozen=True, slots=True)
class ValidatedFilter:
    """A filter the platform is willing to execute, in canonical form."""

    expression: FilterGroup
    canonical: dict[str, Any]
    canonical_hash: str
    field_dictionary_version: str
    field_ids: tuple[str, ...]
    condition_count: int
    depth: int
    #: Field definitions the expression touched, for explainability.
    fields: tuple[FilterFieldDefinition, ...] = ()

    @property
    def is_empty(self) -> bool:
        return self.condition_count == 0


def combine_expressions(
    *nodes: FilterNode | None, operator: LogicalOperator = LogicalOperator.AND
) -> FilterGroup:
    """Join expressions without altering any of them.

    This is how a preset and a user's own conditions are combined: both survive
    verbatim as children of one group, so the preset's identity and version stay
    resolvable and the custom part stays separable.
    """
    children: list[FilterNode] = []
    for node in nodes:
        if node is None:
            continue
        if isinstance(node, FilterGroup) and node.is_empty:
            continue
        children.append(node)
    return FilterGroup(operator=operator, children=tuple(children))


def _coerce_value(
    value: Any,
    definition: FilterFieldDefinition,
    *,
    path: str,
    limits: FilterLimits,
    issues: list[FilterValidationIssue],
) -> Any:
    data_type = definition.data_type
    if value is None:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="null_value",
                message="a comparison value may not be null; use the missing/present "
                "operators to ask about absence",
                field_id=definition.id,
            )
        )
        return None
    if data_type is FilterDataType.BOOLEAN:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="unexpected_value",
                message="boolean fields are filtered with is_true/is_false and take no value",
                field_id=definition.id,
            )
        )
        return None
    if data_type in NUMERIC_DATA_TYPES:
        if isinstance(value, bool):
            issues.append(
                FilterValidationIssue(
                    path=path,
                    code="type_mismatch",
                    message="a numeric field cannot be compared against a boolean",
                    field_id=definition.id,
                )
            )
            return None
        try:
            number: Any = (
                int(value)
                if data_type in (FilterDataType.INTEGER, FilterDataType.GENOMIC_POSITION)
                else float(value)
            )
        except (TypeError, ValueError):
            issues.append(
                FilterValidationIssue(
                    path=path,
                    code="type_mismatch",
                    message=f"value is not a valid {data_type.value}",
                    field_id=definition.id,
                    detail={"value": str(value)},
                )
            )
            return None
        if data_type is FilterDataType.GENOMIC_POSITION and number < 0:
            issues.append(
                FilterValidationIssue(
                    path=path,
                    code="out_of_range",
                    message="a genomic position cannot be negative",
                    field_id=definition.id,
                )
            )
            return None
        return number
    if data_type is FilterDataType.DATETIME:
        if not isinstance(value, str):
            issues.append(
                FilterValidationIssue(
                    path=path,
                    code="type_mismatch",
                    message="a date/time value must be an ISO-8601 string",
                    field_id=definition.id,
                )
            )
            return None
        try:
            datetime.fromisoformat(value)
        except ValueError:
            issues.append(
                FilterValidationIssue(
                    path=path,
                    code="invalid_format",
                    message="a date/time value must be an ISO-8601 string",
                    field_id=definition.id,
                )
            )
            return None
        return value
    # string, categorical, identifier
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        issues.append(
            FilterValidationIssue(
                path=path,
                code="type_mismatch",
                message=f"value is not a valid {data_type.value}",
                field_id=definition.id,
            )
        )
        return None
    text = str(value)
    if len(text) > limits.max_value_length:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="value_too_long",
                message="comparison value exceeds the configured maximum length",
                field_id=definition.id,
                detail={"max_value_length": limits.max_value_length},
            )
        )
        return None
    if (
        definition.allowed_values is not None
        and definition.allowed_values
        and text not in definition.allowed_values
    ):
        issues.append(
            FilterValidationIssue(
                path=path,
                code="value_not_allowed",
                message="value is not one of the values this field admits",
                field_id=definition.id,
                detail={"allowed_values": list(definition.allowed_values)},
            )
        )
        return None
    return text


def _validate_condition(
    condition: FilterCondition,
    *,
    path: str,
    registry: FilterFieldRegistry,
    available_field_ids: frozenset[str] | None,
    limits: FilterLimits,
    issues: list[FilterValidationIssue],
) -> tuple[FilterCondition, FilterFieldDefinition | None]:
    definition = registry.get(condition.field_id)
    if definition is None:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="unknown_field",
                message="no such filterable field",
                field_id=condition.field_id,
            )
        )
        return condition, None
    if not definition.available or not definition.filterable:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="field_unavailable",
                message="this field is not currently filterable on this platform",
                field_id=definition.id,
            )
        )
        return condition, definition
    if available_field_ids is not None and definition.id not in available_field_ids:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="field_not_in_context",
                message="the selected data does not contain this field",
                field_id=definition.id,
            )
        )
        return condition, definition
    if not definition.supports(condition.operator):
        issues.append(
            FilterValidationIssue(
                path=path,
                code="unsupported_operator",
                message="this operator cannot be applied to this field",
                field_id=definition.id,
                detail={
                    "operator": condition.operator.value,
                    "supported_operators": [
                        operator.value for operator in definition.supported_operators
                    ],
                },
            )
        )
        return condition, definition
    if (
        condition.value_type is not None
        and condition.value_type is not definition.data_type
    ):
        issues.append(
            FilterValidationIssue(
                path=path,
                code="value_type_mismatch",
                message="the declared value type does not match the field's type in "
                "the current field dictionary",
                field_id=definition.id,
                detail={
                    "declared": condition.value_type.value,
                    "dictionary": definition.data_type.value,
                    "dictionary_version": registry.version,
                },
            )
        )
        return condition, definition

    arity = operator_arity(condition.operator)
    values = tuple(condition.values)
    if arity is OperatorArity.NONE and values:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="unexpected_value",
                message="this operator takes no value",
                field_id=definition.id,
            )
        )
        return condition, definition
    if arity is OperatorArity.ONE and len(values) != 1:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="wrong_value_count",
                message="this operator takes exactly one value",
                field_id=definition.id,
                detail={"supplied": len(values)},
            )
        )
        return condition, definition
    if arity is OperatorArity.TWO and len(values) != 2:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="wrong_value_count",
                message="this operator takes exactly two values (lower and upper bound)",
                field_id=definition.id,
                detail={"supplied": len(values)},
            )
        )
        return condition, definition
    if arity is OperatorArity.MANY:
        if not values:
            issues.append(
                FilterValidationIssue(
                    path=path,
                    code="wrong_value_count",
                    message="this operator requires at least one value",
                    field_id=definition.id,
                )
            )
            return condition, definition
        if len(values) > limits.max_values_per_condition:
            issues.append(
                FilterValidationIssue(
                    path=path,
                    code="too_many_values",
                    message="value list exceeds the configured maximum",
                    field_id=definition.id,
                    detail={
                        "supplied": len(values),
                        "max_values_per_condition": limits.max_values_per_condition,
                    },
                )
            )
            return condition, definition

    coerced = tuple(
        _coerce_value(
            value,
            definition,
            path=f"{path}.values[{index}]",
            limits=limits,
            issues=issues,
        )
        for index, value in enumerate(values)
    )
    if arity is OperatorArity.TWO and all(item is not None for item in coerced):
        lower, upper = coerced
        try:
            if lower > upper:  # type: ignore[operator]
                issues.append(
                    FilterValidationIssue(
                        path=path,
                        code="invalid_range",
                        message="the lower bound of a range must not exceed the upper bound",
                        field_id=definition.id,
                    )
                )
        except TypeError:
            issues.append(
                FilterValidationIssue(
                    path=path,
                    code="invalid_range",
                    message="range bounds are not comparable",
                    field_id=definition.id,
                )
            )
    return (
        FilterCondition(
            field_id=definition.id,
            operator=condition.operator,
            values=coerced,
            value_type=definition.data_type,
            negated=condition.negated,
            field_definition_version=definition.version,
            display_label=condition.display_label or definition.label,
            metadata=dict(condition.metadata),
        ),
        definition,
    )


def _validate_node(
    node: FilterNode,
    *,
    path: str,
    registry: FilterFieldRegistry,
    available_field_ids: frozenset[str] | None,
    limits: FilterLimits,
    issues: list[FilterValidationIssue],
    touched: list[FilterFieldDefinition],
) -> FilterNode:
    if isinstance(node, FilterCondition):
        validated, definition = _validate_condition(
            node,
            path=path,
            registry=registry,
            available_field_ids=available_field_ids,
            limits=limits,
            issues=issues,
        )
        if definition is not None:
            touched.append(definition)
        return validated
    if node.operator is LogicalOperator.NOT and len(node.children) != 1:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="invalid_group",
                message="a NOT group must contain exactly one child",
            )
        )
    if not node.children:
        issues.append(
            FilterValidationIssue(
                path=path,
                code="empty_group",
                message="a logical group must contain at least one condition",
            )
        )
    children = tuple(
        _validate_node(
            child,
            path=f"{path}.children[{index}]",
            registry=registry,
            available_field_ids=available_field_ids,
            limits=limits,
            issues=issues,
            touched=touched,
        )
        for index, child in enumerate(node.children)
    )
    return FilterGroup(operator=node.operator, children=children)


def validate_filter(
    expression: FilterNode,
    *,
    registry: FilterFieldRegistry,
    limits: FilterLimits | None = None,
    available_field_ids: frozenset[str] | None = None,
    allow_empty: bool = True,
) -> ValidatedFilter:
    """Validate, coerce and canonicalize an expression, or raise with all findings."""
    limits = limits or FilterLimits()
    issues: list[FilterValidationIssue] = []
    touched: list[FilterFieldDefinition] = []

    conditions = iter_conditions(expression)
    if not conditions and not allow_empty:
        raise ValidationError(
            "a filter must contain at least one condition",
            details={"issues": [{"path": "$", "code": "empty_filter"}]},
        )

    depth = node_depth(expression)
    if depth > limits.max_depth:
        issues.append(
            FilterValidationIssue(
                path="$",
                code="too_deep",
                message="filter expression is nested more deeply than allowed",
                detail={"depth": depth, "max_depth": limits.max_depth},
            )
        )
    if len(conditions) > limits.max_conditions:
        issues.append(
            FilterValidationIssue(
                path="$",
                code="too_many_conditions",
                message="filter expression contains more conditions than allowed",
                detail={
                    "conditions": len(conditions),
                    "max_conditions": limits.max_conditions,
                },
            )
        )
    text_matches = sum(
        1 for condition in conditions if condition.operator in TEXT_MATCH_OPERATORS
    )
    if text_matches > limits.max_text_match_conditions:
        issues.append(
            FilterValidationIssue(
                path="$",
                code="too_many_text_matches",
                message="filter expression contains more text-matching conditions than "
                "allowed; text matching is the most expensive predicate the engine runs",
                detail={
                    "text_match_conditions": text_matches,
                    "max_text_match_conditions": limits.max_text_match_conditions,
                },
            )
        )

    # Guard the tree walk itself: a pathological expression is refused on its
    # size before every node is visited.
    if issues and any(issue.code in {"too_deep", "too_many_conditions"} for issue in issues):
        raise ValidationError(
            "filter expression exceeds the configured limits",
            details={"issues": [issue.as_dict() for issue in issues]},
        )

    validated = _validate_node(
        expression,
        path="$",
        registry=registry,
        available_field_ids=available_field_ids,
        limits=limits,
        issues=issues,
        touched=touched,
    )

    # "No filter at all" is a legitimate request when the caller allows it: the
    # root group is then empty on purpose, and only the root may be.
    if allow_empty and not conditions:
        issues[:] = [
            issue
            for issue in issues
            if not (issue.path == "$" and issue.code == "empty_group")
        ]

    # A position range is only meaningful on a stated contig. The condition pair
    # is required rather than assumed, so the platform never invents a contig.
    position_fields = {
        definition.id
        for definition in touched
        if definition.data_type is FilterDataType.GENOMIC_POSITION
    }
    if position_fields:
        contig_present = any(
            condition.field_id == "contig"
            and condition.operator not in PRESENCE_OPERATORS
            for condition in iter_conditions(validated)
        )
        if not contig_present:
            issues.append(
                FilterValidationIssue(
                    path="$",
                    code="position_without_contig",
                    message="a position condition requires a contig condition in the "
                    "same expression",
                    detail={"position_fields": sorted(position_fields)},
                )
            )

    if issues:
        raise ValidationError(
            "filter expression is not valid",
            details={"issues": [issue.as_dict() for issue in issues]},
        )

    canonical_expression = _as_group(canonicalize(validated))
    canonical = canonical_payload(canonical_expression)
    encoded = canonical_json(canonical_expression).encode("utf-8")
    if len(encoded) > limits.max_expression_bytes:
        raise ValidationError(
            "filter expression is larger than allowed",
            details={
                "issues": [
                    FilterValidationIssue(
                        path="$",
                        code="expression_too_large",
                        message="canonical filter expression exceeds the configured size",
                        detail={
                            "bytes": len(encoded),
                            "max_expression_bytes": limits.max_expression_bytes,
                        },
                    ).as_dict()
                ]
            },
        )

    unique_fields: dict[str, FilterFieldDefinition] = {}
    for definition in touched:
        unique_fields.setdefault(definition.id, definition)
    return ValidatedFilter(
        expression=canonical_expression,
        canonical=canonical,
        canonical_hash=canonical_hash(canonical_expression),
        field_dictionary_version=registry.version,
        field_ids=tuple(sorted(unique_fields)),
        condition_count=len(conditions),
        depth=depth,
        fields=tuple(unique_fields.values()),
    )


def _as_group(node: FilterNode) -> FilterGroup:
    if isinstance(node, FilterGroup):
        return node
    return FilterGroup(operator=LogicalOperator.AND, children=(node,))


def expression_size(node: FilterNode) -> int:
    return node_count(node)


def operator_is_list(operator: FilterOperator) -> bool:
    return operator in LIST_OPERATORS


__all__ = [
    "FilterLimits",
    "FilterValidationIssue",
    "ValidatedFilter",
    "combine_expressions",
    "expression_size",
    "operator_is_list",
    "validate_filter",
]
