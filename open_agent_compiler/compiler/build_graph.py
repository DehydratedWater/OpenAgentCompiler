"""Derive the agent compilation order from subagent references.

Replaces the hand-maintained `collect_all_agents()` ordering list that
pre-framework deployments carried. Orchestrators reference subagents through their
`subagents: list[AgentHeader]` field; this module reads those references
out of a resolved tree and returns the slots in dependency order:

  parents (orchestrators) first → children (subagents) last

Order matters when a later phase writes parent stubs that subagents
overwrite, when running per-agent tests where a subagent test depends
on its orchestrator's compiled artifact, or when reporting build progress
so the most important agents are visible first.

Resolution model: the resolved tree from AgentRegistry.resolve_config()
is keyed by slot name. Each variant's subagent references are
AgentHeader instances carrying an agent_id. We map every variant's
header.agent_id back to its slot name so we can express dependencies as
slot → slot.

Subagent references whose agent_id is not present in the resolved tree
(compiled separately or not at all) are surfaced by
find_orphan_subagent_refs() so callers can choose to warn or error.
"""

from __future__ import annotations

from collections import defaultdict, deque

from open_agent_compiler.model.core.agent_model import AgentVariant


def _agent_id_to_slot(variants: dict[str, AgentVariant]) -> dict[str, str]:
    """Map each variant's agent_id → its slot name."""
    return {v.agent_definition.header.agent_id: slot for slot, v in variants.items()}


def build_dependency_graph(
    variants: dict[str, AgentVariant],
) -> dict[str, set[str]]:
    """slot_name → set of slot_names it references as subagents.

    Edges point parent → child. Subagent references whose agent_id isn't
    in the tree are silently dropped here (use find_orphan_subagent_refs
    to surface them separately).
    """
    id_to_slot = _agent_id_to_slot(variants)
    edges: dict[str, set[str]] = defaultdict(set)
    for slot, variant in variants.items():
        for sub_header in variant.agent_definition.subagents:
            sub_slot = id_to_slot.get(sub_header.agent_id)
            if sub_slot is not None and sub_slot != slot:
                edges[slot].add(sub_slot)
    return dict(edges)


def find_orphan_subagent_refs(
    variants: dict[str, AgentVariant],
) -> dict[str, list[str]]:
    """slot_name → list of subagent agent_ids it references but tree lacks."""
    id_to_slot = _agent_id_to_slot(variants)
    orphans: dict[str, list[str]] = {}
    for slot, variant in variants.items():
        missing = [
            sub.agent_id for sub in variant.agent_definition.subagents
            if sub.agent_id not in id_to_slot
        ]
        if missing:
            orphans[slot] = missing
    return orphans


def find_cycles(variants: dict[str, AgentVariant]) -> list[list[str]]:
    """Return any cycles as lists of slot names; empty list when acyclic.

    Cycles in the orchestrator/subagent graph almost always indicate a
    design error (a subagent that recursively dispatches to its own
    orchestrator). Detect early; let the caller decide policy.
    """
    edges = build_dependency_graph(variants)
    cycles: list[list[str]] = []
    visited: set[str] = set()
    stack: list[str] = []
    on_stack: set[str] = set()

    def dfs(node: str) -> None:
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for nxt in edges.get(node, ()):
            if nxt not in visited:
                dfs(nxt)
            elif nxt in on_stack:
                idx = stack.index(nxt)
                cycles.append(stack[idx:] + [nxt])
        stack.pop()
        on_stack.remove(node)

    for node in variants:
        if node not in visited:
            dfs(node)
    return cycles


def topological_order(variants: dict[str, AgentVariant]) -> list[str]:
    """Slot names ordered parents-before-children (Kahn's algorithm).

    Ties broken alphabetically for stable output. Raises ValueError if
    the graph contains a cycle — call find_cycles() first if you want
    to inspect them before failing.
    """
    cycles = find_cycles(variants)
    if cycles:
        raise ValueError(
            "Agent dependency graph has cycles: "
            + ", ".join("->".join(c) for c in cycles)
        )

    edges = build_dependency_graph(variants)
    # incoming[child] = number of parents not yet emitted
    incoming: dict[str, int] = {slot: 0 for slot in variants}
    for parents in edges.values():
        for child in parents:
            incoming[child] = incoming.get(child, 0) + 1

    queue: deque[str] = deque(
        sorted(slot for slot, n in incoming.items() if n == 0)
    )
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for child in sorted(edges.get(node, ())):
            incoming[child] -= 1
            if incoming[child] == 0:
                queue.append(child)
    if len(order) != len(variants):
        # Should be unreachable given the cycle check above, but guard
        # in case `variants` contains slot names not present in
        # build_dependency_graph (which it always does — that's enforced
        # by construction). Belt-and-suspenders.
        raise ValueError("topological_order failed to emit every slot")
    return order
