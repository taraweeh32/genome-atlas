"""The filter expression model: conditions and nested logical groups.

A filter expression is *data*, never code. It is a tree of two node kinds — a
condition (one field, one operator, its values) and a group (a logical connective
over child nodes) — which can be serialized, stored, hashed, compared and
compiled. Nothing in this module evaluates anything or touches a database; a
validated expression is handed to the analytical layer, which compiles it into a
parameterized query.

Parsing is deliberately strict. An unknown key, an unknown operator or a value
list of the wrong shape is rejected with a path into the tree rather than
repaired, because silently "fixing" a scientific filter changes which variants a
clinician sees.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from app.domain.errors import ValidationError
from app.domain.query.operators import (
    FilterDataType,
    FilterOperator,
    LogicalOperator,
)

#: Node kind discriminators used in the serialized form.
CONDITION_KIND = "condition"
GROUP_KIND = "group"


@dataclass(frozen=True, slots=True)
class FilterCondition:
    """One declared condition over one registered field.

    ``value_type`` is carried explicitly even though the field dictionary also
    declares it: an expression stored last year must remain interpretable against
    the dictionary version it was written for, and a mismatch is a validation
    finding rather than something to guess about.
    """

    field_id: str
    operator: FilterOperator
    values: tuple[Any, ...] = ()
    value_type: FilterDataType | None = None
    negated: bool = False
    #: Dictionary version the condition was authored against, when known.
    field_definition_version: str | None = None
    #: Human-facing label captured at authoring time, for explainability only.
    #: Never used to resolve the field.
    display_label: str | None = None
    #: Declared, non-executable metadata (units, source note, normalization note).
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return CONDITION_KIND

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": CONDITION_KIND,
            "field_id": self.field_id,
            "operator": self.operator.value,
            "values": list(self.values),
            "negated": self.negated,
        }
        if self.value_type is not None:
            payload["value_type"] = self.value_type.value
        if self.field_definition_version is not None:
            payload["field_definition_version"] = self.field_definition_version
        if self.display_label is not None:
            payload["display_label"] = self.display_label
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    def with_values(self, values: tuple[Any, ...]) -> FilterCondition:
        return replace(self, values=values)


@dataclass(frozen=True, slots=True)
class FilterGroup:
    """A logical connective over child nodes. Groups may nest."""

    operator: LogicalOperator = LogicalOperator.AND
    children: tuple["FilterNode", ...] = ()

    @property
    def kind(self) -> str:
        return GROUP_KIND

    @property
    def is_empty(self) -> bool:
        return len(self.children) == 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": GROUP_KIND,
            "operator": self.operator.value,
            "children": [child.to_payload() for child in self.children],
        }

    def with_children(self, children: tuple["FilterNode", ...]) -> FilterGroup:
        return replace(self, children=children)


FilterNode = FilterCondition | FilterGroup

EMPTY_FILTER = FilterGroup(operator=LogicalOperator.AND, children=())

_CONDITION_KEYS = frozenset(
    {
        "kind",
        "field_id",
        "operator",
        "values",
        "value_type",
        "negated",
        "field_definition_version",
        "display_label",
        "metadata",
    }
)
_GROUP_KEYS = frozenset({"kind", "operator", "children"})


def _fail(message: str, path: str, **details: Any) -> ValidationError:
    return ValidationError(message, details={"path": path, **details})


def node_from_payload(payload: Any, *, path: str = "$", depth: int = 0, max_depth: int = 32) -> FilterNode:
    """Parse a serialized node. Structural checks only; semantics come later.

    ``max_depth`` here is a parser guard against a hostile payload, not the
    configured filter-depth policy: validation applies that separately, so the
    limit users are told about stays configuration-driven.
    """
    if depth > max_depth:
        raise _fail("filter expression is nested too deeply", path)
    if not isinstance(payload, dict):
        raise _fail("filter node must be an object", path)
    kind = payload.get("kind", GROUP_KIND if "children" in payload else CONDITION_KIND)
    if kind == GROUP_KIND:
        unknown = set(payload) - _GROUP_KEYS
        if unknown:
            raise _fail(
                "unknown keys in filter group", path, unknown_keys=sorted(unknown)
            )
        raw_operator = payload.get("operator", LogicalOperator.AND.value)
        try:
            operator = LogicalOperator(str(raw_operator))
        except ValueError as error:
            raise _fail(
                "unsupported logical operator", path, operator=str(raw_operator)
            ) from error
        raw_children = payload.get("children", [])
        if not isinstance(raw_children, list):
            raise _fail("group children must be a list", path)
        children = tuple(
            node_from_payload(
                child,
                path=f"{path}.children[{index}]",
                depth=depth + 1,
                max_depth=max_depth,
            )
            for index, child in enumerate(raw_children)
        )
        if operator is LogicalOperator.NOT and len(children) != 1:
            raise _fail(
                "a NOT group must contain exactly one child",
                path,
                child_count=len(children),
            )
        return FilterGroup(operator=operator, children=children)

    if kind != CONDITION_KIND:
        raise _fail("unknown filter node kind", path, kind=str(kind))
    unknown = set(payload) - _CONDITION_KEYS
    if unknown:
        raise _fail("unknown keys in filter condition", path, unknown_keys=sorted(unknown))
    field_id = payload.get("field_id")
    if not isinstance(field_id, str) or not field_id.strip():
        raise _fail("a filter condition requires a field identifier", path)
    raw_operator = payload.get("operator")
    try:
        operator = FilterOperator(str(raw_operator))
    except ValueError as error:
        raise _fail(
            "unsupported filter operator", path, operator=str(raw_operator)
        ) from error
    raw_values = payload.get("values", [])
    if raw_values is None:
        raw_values = []
    if not isinstance(raw_values, list):
        raise _fail("condition values must be a list", path)
    for index, value in enumerate(raw_values):
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            # Only scalars may cross this boundary. A nested object or list here
            # is how an expression language starts to grow, and it will not.
            raise _fail(
                "condition values must be scalar",
                f"{path}.values[{index}]",
                value_type=type(value).__name__,
            )
    value_type: FilterDataType | None = None
    if "value_type" in payload and payload["value_type"] is not None:
        try:
            value_type = FilterDataType(str(payload["value_type"]))
        except ValueError as error:
            raise _fail(
                "unsupported value type", path, value_type=str(payload["value_type"])
            ) from error
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise _fail("condition metadata must be an object", path)
    negated = payload.get("negated", False)
    if not isinstance(negated, bool):
        raise _fail("negated must be a boolean", path)
    display_label = payload.get("display_label")
    if display_label is not None and not isinstance(display_label, str):
        raise _fail("display_label must be a string", path)
    definition_version = payload.get("field_definition_version")
    if definition_version is not None and not isinstance(definition_version, str):
        raise _fail("field_definition_version must be a string", path)
    return FilterCondition(
        field_id=field_id.strip(),
        operator=operator,
        values=tuple(raw_values),
        value_type=value_type,
        negated=negated,
        field_definition_version=definition_version,
        display_label=display_label,
        metadata=dict(metadata),
    )


def group_from_payload(payload: Any, *, max_depth: int = 32) -> FilterGroup:
    """Parse a payload that must be a group; a bare condition is wrapped in AND."""
    node = node_from_payload(payload, max_depth=max_depth)
    if isinstance(node, FilterCondition):
        return FilterGroup(operator=LogicalOperator.AND, children=(node,))
    return node


def iter_conditions(node: FilterNode) -> tuple[FilterCondition, ...]:
    if isinstance(node, FilterCondition):
        return (node,)
    collected: list[FilterCondition] = []
    for child in node.children:
        collected.extend(iter_conditions(child))
    return tuple(collected)


def node_depth(node: FilterNode) -> int:
    if isinstance(node, FilterCondition):
        return 1
    if not node.children:
        return 1
    return 1 + max(node_depth(child) for child in node.children)


def node_count(node: FilterNode) -> int:
    if isinstance(node, FilterCondition):
        return 1
    return 1 + sum(node_count(child) for child in node.children)


__all__ = [
    "CONDITION_KIND",
    "EMPTY_FILTER",
    "GROUP_KIND",
    "FilterCondition",
    "FilterGroup",
    "FilterNode",
    "group_from_payload",
    "iter_conditions",
    "node_count",
    "node_depth",
    "node_from_payload",
]
