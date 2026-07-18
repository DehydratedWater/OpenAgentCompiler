"""Branch test runner — drive an orchestration path, evaluate its trajectory.

No models: the scripted/mock invokers replay a chain so the runner + evaluators
are exercised deterministically (the gate tier).
"""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.branch_model import BranchTest
from open_agent_compiler.model.core.test_model import SubstringEvaluator, Turn
from open_agent_compiler.testing.branch import (
    mock_chain_invoker,
    run_branch_test,
    scripted_invoker,
)


def test_branch_passes_when_chain_matches_path():
    test = BranchTest(
        name="priority-chain",
        entry_agent="persona/orchestrator",
        prompt="What should I focus on, and schedule it?",
        path=("context_analyzer", "priority_planner", "todo"),
    )
    invoker = scripted_invoker(
        ["context_analyzer", "priority_planner", "todo"],
        output="Scheduled your top priority.",
    )
    result = run_branch_test(test, invoker)
    assert result.passed
    assert result.score == 1.0
    assert result.chain == ["context_analyzer", "priority_planner", "todo"]


def test_branch_fails_on_wrong_order():
    test = BranchTest(
        name="priority-chain",
        entry_agent="persona/orchestrator",
        prompt="focus + schedule",
        path=("context_analyzer", "priority_planner", "todo"),
    )
    # planner dispatched before analyzer → path broken
    invoker = scripted_invoker(["priority_planner", "context_analyzer", "todo"])
    result = run_branch_test(test, invoker)
    assert not result.passed
    assert result.score < 1.0


def test_branch_combines_path_and_output_evaluators():
    test = BranchTest(
        name="chain-and-says-scheduled",
        entry_agent="persona/orchestrator",
        prompt="focus + schedule",
        path=("context_analyzer", "todo"),
        evaluators=(SubstringEvaluator(needle="scheduled", case_sensitive=False),),
    )
    ok = scripted_invoker(["context_analyzer", "todo"], output="All Scheduled!")
    assert run_branch_test(test, ok).passed

    # right chain, wrong output → fails on the substring evaluator
    bad = scripted_invoker(["context_analyzer", "todo"], output="done")
    r = run_branch_test(test, bad)
    assert not r.passed


def test_mock_chain_invoker_uses_declared_path_and_mocks():
    test = BranchTest(
        name="food-plan",
        entry_agent="food/orchestrator",
        prompt="plan dinner",
        path=("recipe_parser", "meal_planner"),
        subagent_mocks={"meal_planner": "Pasta tonight."},
        evaluators=(SubstringEvaluator(needle="Pasta"),),
    )
    result = run_branch_test(test, mock_chain_invoker)
    assert result.passed
    assert result.chain == ["recipe_parser", "meal_planner"]


def test_branch_with_no_evaluators_is_not_a_pass():
    # A branch that asserts nothing is a misconfiguration, not a vacuous pass.
    test = BranchTest(
        name="empty",
        entry_agent="x",
        prompt="go",
    )
    result = run_branch_test(test, scripted_invoker(["a", "b"]))
    assert not result.passed
    assert result.score == 0.0


def test_branch_multi_turn_validates():
    test = BranchTest(
        name="mt",
        entry_agent="x",
        turns=(Turn(prompt="step 1"), Turn(prompt="step 2")),
        path=("a",),
    )
    assert test.is_multi_turn
    assert run_branch_test(test, scripted_invoker(["a"])).passed


def test_prompt_xor_turns_enforced():
    with pytest.raises(ValueError):
        BranchTest(name="bad", entry_agent="x", prompt="a", turns=(Turn(prompt="b"),))
    with pytest.raises(ValueError):
        BranchTest(name="bad", entry_agent="x")
