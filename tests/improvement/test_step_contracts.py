"""StepContract — per-step subagent assertions inside a branch run."""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.branch_model import BranchTest, StepContract
from open_agent_compiler.model.core.test_model import (
    JsonPathEvaluator,
    SubstringEvaluator,
)
from open_agent_compiler.testing.branch import (
    BranchTrajectory,
    evaluate_step_contracts,
    run_branch_test,
    scripted_invoker,
)
from open_agent_compiler.testing.evaluation import ToolCallRecord


def _test(**kwargs) -> BranchTest:
    base = dict(name="t", entry_agent="orch", prompt="do it")
    base.update(kwargs)
    return BranchTest(**base)


def test_contract_checks_subagent_args_and_output() -> None:
    test = _test(
        path=("food_suggester",),
        step_contracts=(
            StepContract(
                step="food_suggester",
                input_evaluators=(
                    # The orchestrator must forward the dietary restriction.
                    JsonPathEvaluator(path="context.diet", expected="vegan"),
                ),
                output_evaluators=(SubstringEvaluator(needle="tofu"),),
            ),
        ),
    )
    good = scripted_invoker(
        [("food_suggester", {"context": {"diet": "vegan"}})], output="tofu bowl",
    )

    # scripted_invoker doesn't set per-call output — build trajectory directly.
    def invoke(_t):
        return BranchTrajectory(
            output="tofu bowl",
            tool_calls=[
                ToolCallRecord(
                    name="food_suggester",
                    args={"context": {"diet": "vegan"}},
                    output="try a tofu bowl",
                )
            ],
        )

    result = run_branch_test(test, invoke)
    assert result.passed, [r.evidence for r in result.results]
    names = [r.evaluator_name for r in result.results]
    assert any(n.startswith("step:food_suggester:input") for n in names)
    assert any(n.startswith("step:food_suggester:output") for n in names)
    del good


def test_contract_fails_when_context_not_forwarded() -> None:
    test = _test(
        path=("food_suggester",),
        step_contracts=(
            StepContract(
                step="food_suggester",
                input_evaluators=(
                    JsonPathEvaluator(path="context.diet", expected="vegan"),
                ),
            ),
        ),
    )
    dropped_context = scripted_invoker([("food_suggester", {"context": {}})])
    result = run_branch_test(test, dropped_context)
    assert not result.passed
    failing = [r for r in result.results if not r.passed]
    assert any("step:food_suggester:input" in r.evaluator_name for r in failing)


def test_required_step_never_dispatched_fails_branch() -> None:
    test = _test(
        path=(),
        evaluators=(SubstringEvaluator(needle="ok"),),
        step_contracts=(StepContract(step="validator"),),
    )
    result = run_branch_test(test, scripted_invoker(["other_agent"], output="ok"))
    assert not result.passed
    assert any("never dispatched" in r.evidence for r in result.results)


def test_optional_step_never_dispatched_skips() -> None:
    test = _test(
        path=(),
        evaluators=(SubstringEvaluator(needle="ok"),),
        step_contracts=(
            StepContract(
                step="enricher",
                required=False,
                output_evaluators=(SubstringEvaluator(needle="x"),),
            ),
        ),
    )
    result = run_branch_test(test, scripted_invoker(["other"], output="ok"))
    assert result.passed
    assert any(r.skipped for r in result.results)


def test_every_occurrence_is_checked() -> None:
    test = _test(
        path=(),
        evaluators=(SubstringEvaluator(needle="ok"),),
        step_contracts=(
            StepContract(
                step="writer",
                output_evaluators=(SubstringEvaluator(needle="draft"),),
            ),
        ),
    )

    def invoke(_t):
        return BranchTrajectory(
            output="ok",
            tool_calls=[
                ToolCallRecord(name="writer", output="draft one"),
                ToolCallRecord(name="writer", output="garbage"),
            ],
        )

    result = run_branch_test(test, invoke)
    assert not result.passed
    names = [r.evaluator_name for r in result.results if not r.passed]
    assert any(n.startswith("step:writer[1]:output") for n in names)


def test_evaluate_step_contracts_standalone() -> None:
    test = _test(
        step_contracts=(
            StepContract(
                step="a",
                input_evaluators=(JsonPathEvaluator(path="k", expected=1),),
            ),
        ),
    )
    trajectory = BranchTrajectory(
        tool_calls=[ToolCallRecord(name="a", args={"k": 1})],
    )
    results = evaluate_step_contracts(test, trajectory)
    assert len(results) == 1 and results[0].passed


def test_contract_must_assert_something() -> None:
    with pytest.raises(ValueError):
        StepContract(step="x", required=False)
    # required=True alone is a valid presence check.
    StepContract(step="x")


def test_contracts_fold_into_branch_score() -> None:
    test = _test(
        path=("a",),
        step_contracts=(
            StepContract(step="a", output_evaluators=(SubstringEvaluator(needle="hit"),)),
        ),
    )

    def invoke(_t):
        return BranchTrajectory(
            output="anything",
            tool_calls=[ToolCallRecord(name="a", output="miss")],
        )

    result = run_branch_test(test, invoke)
    # path passes (1.0), contract output fails (0.0) → mean 0.5, passed False.
    assert result.score == pytest.approx(0.5)
    assert not result.passed
