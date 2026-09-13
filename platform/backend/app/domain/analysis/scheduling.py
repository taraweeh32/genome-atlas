"""Capability- and resource-aware node selection.

A pure function over the node inventory: given what a job requires and what the
registered nodes advertise, return the node that should run it, or a structured
reason why none can. No side effects, no I/O, no scientific knowledge — a
capability is an opaque identifier declared by the scientific subsystem.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.analysis.entities import ComputeNode
from app.domain.analysis.policies import ResourceRequirements
from app.domain.value_objects.enums import NodeClass


class SelectionReason:
    """Why no node was selected. Surfaced verbatim to operators."""

    NO_NODES_REGISTERED = "no_nodes_registered"
    NO_NODE_FOR_CLASS = "no_node_for_class"
    NO_NODE_FOR_QUEUE = "no_node_for_queue"
    NO_NODE_WITH_CAPABILITY = "no_node_with_capability"
    NO_NODE_WITH_RESOURCES = "no_node_with_resources"
    NO_NODE_WITH_CAPACITY = "no_node_with_capacity"


@dataclass(frozen=True, slots=True)
class NodeSelection:
    node: ComputeNode | None
    reason: str | None = None
    #: Nodes that matched class/queue but failed a later filter, for diagnostics.
    considered: tuple[str, ...] = ()

    @property
    def selected(self) -> bool:
        return self.node is not None


def _fits(node: ComputeNode, requirements: ResourceRequirements) -> bool:
    profile = node.resource_profile or {}

    def available(key: str, default: int = 0) -> int:
        try:
            return int(profile.get(key, default))
        except (TypeError, ValueError):
            # An unparseable advertisement is treated as *no* capacity: a node
            # must prove it fits, never be assumed to.
            return 0

    return (
        available("cpu_cores") >= requirements.cpu_cores
        and available("memory_mib") >= requirements.memory_mib
        and available("disk_mib") >= requirements.disk_mib
        and available("gpu_count") >= requirements.gpu_count
    )


def select_node(
    nodes: Sequence[ComputeNode],
    *,
    node_class: NodeClass,
    queue: str,
    requirements: ResourceRequirements,
    required_capabilities: Sequence[str] = (),
) -> NodeSelection:
    """Pick the least-loaded schedulable node that satisfies every requirement.

    Filters are applied in order and each one reports its own failure, so an
    operator sees *why* work is not running instead of a bare "pending".
    """
    if not nodes:
        return NodeSelection(node=None, reason=SelectionReason.NO_NODES_REGISTERED)

    by_class = [node for node in nodes if node.node_class is node_class]
    if not by_class:
        return NodeSelection(node=None, reason=SelectionReason.NO_NODE_FOR_CLASS)

    by_queue = [node for node in by_class if not node.queues or queue in node.queues]
    if not by_queue:
        return NodeSelection(
            node=None,
            reason=SelectionReason.NO_NODE_FOR_QUEUE,
            considered=tuple(node.node_key for node in by_class),
        )

    wanted = tuple(dict.fromkeys([*required_capabilities, *requirements.requires_capabilities]))
    by_capability = [
        node for node in by_queue if all(item in node.capabilities for item in wanted)
    ]
    if not by_capability:
        return NodeSelection(
            node=None,
            reason=SelectionReason.NO_NODE_WITH_CAPABILITY,
            considered=tuple(node.node_key for node in by_queue),
        )

    by_resources = [node for node in by_capability if _fits(node, requirements)]
    if not by_resources:
        return NodeSelection(
            node=None,
            reason=SelectionReason.NO_NODE_WITH_RESOURCES,
            considered=tuple(node.node_key for node in by_capability),
        )

    schedulable = [node for node in by_resources if node.is_schedulable]
    if not schedulable:
        return NodeSelection(
            node=None,
            reason=SelectionReason.NO_NODE_WITH_CAPACITY,
            considered=tuple(node.node_key for node in by_resources),
        )

    # Least loaded first, then a stable key so selection is deterministic and
    # therefore reproducible in tests and incident review.
    chosen = min(
        schedulable,
        key=lambda node: (node.active_job_count / max(node.max_concurrency, 1), node.node_key),
    )
    return NodeSelection(node=chosen, considered=tuple(n.node_key for n in schedulable))


__all__ = ["NodeSelection", "SelectionReason", "select_node"]
