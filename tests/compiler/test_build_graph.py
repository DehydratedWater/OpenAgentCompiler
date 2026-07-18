"""Build-order graph: topological sort, cycle detection, orphan refs."""

from __future__ import annotations

import pytest

from open_agent_compiler.compiler.build_graph import (
    build_dependency_graph,
    find_cycles,
    find_orphan_subagent_refs,
    topological_order,
)
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    ModelParameters,
)


def _v(agent_id: str, subagents: list[str] = ()) -> AgentVariant:
    return AgentVariant(
        postfix="", agent_mode="primary",
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id=agent_id, name=agent_id, description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            subagents=[AgentHeader(agent_id=sid, name=sid) for sid in subagents],
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )


def test_build_graph_maps_subagents_to_slots() -> None:
    tree = {
        "orch": _v("orch-id", subagents=["worker-id"]),
        "worker": _v("worker-id"),
    }
    assert build_dependency_graph(tree) == {"orch": {"worker"}}


def test_topological_order_parents_first() -> None:
    tree = {
        "orch": _v("orch-id", subagents=["a-id", "b-id"]),
        "a": _v("a-id", subagents=["leaf-id"]),
        "b": _v("b-id"),
        "leaf": _v("leaf-id"),
    }
    order = topological_order(tree)
    # orch must come before its direct subagents; a must come before leaf.
    assert order.index("orch") < order.index("a")
    assert order.index("orch") < order.index("b")
    assert order.index("a") < order.index("leaf")


def test_topological_order_stable_alphabetical_for_independents() -> None:
    tree = {"z": _v("z-id"), "a": _v("a-id"), "m": _v("m-id")}
    assert topological_order(tree) == ["a", "m", "z"]


def test_find_cycles_returns_empty_for_acyclic() -> None:
    tree = {"orch": _v("orch-id", subagents=["w-id"]), "w": _v("w-id")}
    assert find_cycles(tree) == []


def test_find_cycles_detects_two_node_cycle() -> None:
    tree = {
        "a": _v("a-id", subagents=["b-id"]),
        "b": _v("b-id", subagents=["a-id"]),
    }
    cycles = find_cycles(tree)
    assert cycles
    cycle_nodes = set(cycles[0])
    assert cycle_nodes == {"a", "b"}


def test_topological_order_raises_on_cycle() -> None:
    tree = {
        "a": _v("a-id", subagents=["b-id"]),
        "b": _v("b-id", subagents=["a-id"]),
    }
    with pytest.raises(ValueError, match="cycles"):
        topological_order(tree)


def test_orphan_subagent_refs_reports_missing() -> None:
    tree = {
        "orch": _v("orch-id", subagents=["ghost-id", "present-id"]),
        "present": _v("present-id"),
    }
    orphans = find_orphan_subagent_refs(tree)
    assert orphans == {"orch": ["ghost-id"]}


def test_orphan_subagent_refs_empty_when_all_present() -> None:
    tree = {
        "orch": _v("orch-id", subagents=["w-id"]),
        "w": _v("w-id"),
    }
    assert find_orphan_subagent_refs(tree) == {}


def test_self_loop_is_ignored_in_dependency_graph() -> None:
    # An agent referencing itself wouldn't make sense and would create a
    # one-node cycle. We strip self-edges so the graph reflects real deps.
    tree = {"a": _v("a-id", subagents=["a-id"])}
    assert build_dependency_graph(tree) == {}
    assert topological_order(tree) == ["a"]
