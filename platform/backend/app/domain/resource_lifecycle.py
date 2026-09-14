"""Lifecycle rules shared by every registered scientific resource version.

One place decides which resource-state transitions exist, so annotation
resources, evidence sources and rulesets cannot drift into three different
lifecycles. Activation is always explicit, and a retired or invalidated version
never becomes usable again: whatever named that version must keep pointing at
the same immutable identity.
"""

from __future__ import annotations

from app.domain.errors import ConflictError
from app.domain.value_objects.enums import ScientificResourceState

RESOURCE_STATE_TRANSITIONS: dict[
    ScientificResourceState, frozenset[ScientificResourceState]
] = {
    ScientificResourceState.REGISTERED: frozenset(
        {
            ScientificResourceState.VALIDATING,
            ScientificResourceState.ACTIVE,
            ScientificResourceState.INVALIDATED,
            ScientificResourceState.RETIRED,
        }
    ),
    ScientificResourceState.VALIDATING: frozenset(
        {
            ScientificResourceState.ACTIVE,
            ScientificResourceState.INVALIDATED,
            ScientificResourceState.RETIRED,
        }
    ),
    ScientificResourceState.ACTIVE: frozenset(
        {
            ScientificResourceState.DEPRECATED,
            ScientificResourceState.RETIRED,
            ScientificResourceState.INVALIDATED,
        }
    ),
    ScientificResourceState.DEPRECATED: frozenset(
        {
            ScientificResourceState.ACTIVE,
            ScientificResourceState.RETIRED,
            ScientificResourceState.INVALIDATED,
        }
    ),
    ScientificResourceState.RETIRED: frozenset(),
    ScientificResourceState.INVALIDATED: frozenset(),
}

#: States in which a version may still be named by new work. ``DEPRECATED`` stays
#: usable on purpose: it is a recommendation against new use, and refusing it
#: outright would strand in-flight work.
USABLE_RESOURCE_STATES: frozenset[ScientificResourceState] = frozenset(
    {ScientificResourceState.ACTIVE, ScientificResourceState.DEPRECATED}
)


def check_resource_transition(
    *,
    current: ScientificResourceState,
    target: ScientificResourceState,
    resource_kind: str,
) -> None:
    """Raise unless ``current -> target`` is an allowed transition."""
    if target not in RESOURCE_STATE_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"this {resource_kind} state transition is not allowed",
            details={"from": current.value, "to": target.value},
        )


__all__ = [
    "RESOURCE_STATE_TRANSITIONS",
    "USABLE_RESOURCE_STATES",
    "check_resource_transition",
]
