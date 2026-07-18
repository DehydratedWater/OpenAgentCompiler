"""Branch optimisation — the generic IterativeLoop, driven by branch tests.

A deterministic "model": the invoker_factory reads a marker in the candidate's
system_prompt and returns a chain accordingly. So a prompt mutator that adds the
right marker makes the branch test pass — proving the loop can climb an
orchestrator's routing using only branch-level signal. No network.
"""

from __future__ import annotations

from open_agent_compiler.improvement.branch import (
    branch_component_id,
    build_branch_evaluator,
    build_branch_loop,
)
from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.mutators import IdentityMutator, PromptPrefixMutator
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.branch_model import BranchTest
from open_agent_compiler.testing.branch import scripted_invoker

CHAIN_TEST = BranchTest(
    name="chains-context-then-plan",
    entry_agent="persona/orchestrator",
    prompt="What should I focus on and schedule it?",
    path=("context_analyzer", "priority_planner", "todo"),
)

GOOD_MARKER = "ALWAYS analyze context, then plan, then write the todo."


def invoker_factory(definition: dict):
    """A toy 'model': only a prompt carrying GOOD_MARKER produces the full,
    correctly-ordered chain; otherwise the orchestrator skips planning."""
    prompt = definition.get("system_prompt", "")
    if GOOD_MARKER in prompt:
        return scripted_invoker(
            ["context_analyzer", "priority_planner", "todo"], output="scheduled"
        )
    # bad routing: jumps straight to todo, skips analyze+plan
    return scripted_invoker(["todo"], output="scheduled")


CRITERION = OptimisationCriterion(
    name="branch-chains-correctly",
    criteria=(Criterion(kind="pass_rate", target=1.0, hard=True),),
)


def test_evaluator_scores_baseline_vs_fixed():
    ev = build_branch_evaluator([CHAIN_TEST], invoker_factory)
    bad = ComponentVersion.of("branch:x", "agent", {"system_prompt": "route stuff"})
    good = ComponentVersion.of("branch:x", "agent", {"system_prompt": GOOD_MARKER})
    bad_m = ev(bad)
    good_m = ev(good)
    assert bad_m["pass_rate"] == 0.0 and bad_m["score_floor"] < 1.0
    assert good_m["pass_rate"] == 1.0 and good_m["score_floor"] == 1.0
    # per-test by_name metric is emitted
    assert f"score_floor:by_name:{CHAIN_TEST.name}" in good_m


def test_loop_finds_the_routing_fix():
    loop = build_branch_loop(
        entry_agent="persona/orchestrator",
        entry_definition={"system_prompt": "You route requests."},
        tests=[CHAIN_TEST],
        invoker_factory=invoker_factory,
        mutators=[IdentityMutator(), PromptPrefixMutator(GOOD_MARKER)],
        criterion=CRITERION,
        max_rounds=2,
    )
    result = loop.run()
    best = result.best(metric="pass_rate")
    assert best is not None
    assert best.metrics["pass_rate"] == 1.0
    assert GOOD_MARKER in best.definition["system_prompt"]


def test_component_id_is_namespaced():
    assert branch_component_id("persona/orchestrator") == "branch:persona/orchestrator"
