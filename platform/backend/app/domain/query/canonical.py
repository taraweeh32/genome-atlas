"""Deterministic canonical form and hash for filter expressions.

Reproducibility needs a single answer to "is this the same filter?". Two
expressions a user would call identical — the same two conditions written in the
other order, the same ``IN`` list shuffled, a group wrapping a single condition —
must produce the same bytes, so an execution can be matched against the exact
configuration that produced it.

Only semantics-preserving rewrites are performed:

* field identifiers and operator tokens are lower-cased (identifiers are already
  registry tokens, so case is not information);
* values of commutative list operators are de-duplicated and ordered;
* children of ``AND``/``OR`` groups are ordered by their own canonical bytes,
  because those connectives are commutative;
* a redundant single-child ``AND``/``OR`` wrapper collapses into its child.

Deliberately *not* performed: no De Morgan rewriting, no ``NOT`` pushdown, no
range merging, no operator substitution. Those change what an expression says
about missing values, and a normalizer that changes meaning is a scientific
decision in disguise.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.domain.query.expressions import (
    FilterCondition,
    FilterGroup,
    FilterNode,
)
from app.domain.query.operators import LIST_OPERATORS, LogicalOperator


def _value_sort_key(value: Any) -> tuple[int, str]:
    """Order values across mixed scalar types deterministically."""
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, str(value).lower())
    if isinstance(value, (int, float)):
        return (2, f"{float(value):.17g}")
    return (3, str(value))


def canonicalize(node: FilterNode) -> FilterNode:
    """Return the canonical form of ``node``."""
    if isinstance(node, FilterCondition):
        values = node.values
        if node.operator in LIST_OPERATORS:
            unique: list[Any] = []
            seen: set[tuple[int, str]] = set()
            for value in values:
                key = _value_sort_key(value)
                if key not in seen:
                    seen.add(key)
                    unique.append(value)
            values = tuple(sorted(unique, key=_value_sort_key))
        return FilterCondition(
            field_id=node.field_id.strip().lower(),
            operator=node.operator,
            values=values,
            value_type=node.value_type,
            negated=node.negated,
            field_definition_version=node.field_definition_version,
            display_label=node.display_label,
            metadata=dict(sorted(node.metadata.items())) if node.metadata else {},
        )

    children = tuple(canonicalize(child) for child in node.children)
    if node.operator is LogicalOperator.NOT:
        return FilterGroup(operator=LogicalOperator.NOT, children=children)
    if len(children) == 1 and isinstance(children[0], (FilterCondition, FilterGroup)):
        # A single-child AND/OR carries no information beyond its child.
        return children[0]
    ordered = tuple(
        sorted(children, key=lambda child: json.dumps(child.to_payload(), sort_keys=True))
    )
    return FilterGroup(operator=node.operator, children=ordered)


def canonical_payload(node: FilterNode) -> dict[str, Any]:
    """Canonical serialized form, always shaped as a group for storage."""
    canonical = canonicalize(node)
    if isinstance(canonical, FilterCondition):
        canonical = FilterGroup(operator=LogicalOperator.AND, children=(canonical,))
    return canonical.to_payload()


def canonical_json(node: FilterNode) -> str:
    return json.dumps(
        canonical_payload(node), sort_keys=True, separators=(",", ":"), default=str
    )


def canonical_hash(node: FilterNode) -> str:
    """Stable content hash of the canonical form, prefixed with its algorithm."""
    digest = hashlib.sha256(canonical_json(node).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


__all__ = ["canonical_hash", "canonical_json", "canonical_payload", "canonicalize"]
