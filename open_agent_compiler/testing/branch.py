"""Branch test runner — drive an orchestration branch, evaluate its trajectory.

`run_branch_test` is tier-agnostic: it hands the test to a `BranchInvoker`
(which the consumer wires to either a deterministic mock replay or a live
`opencode` run) and evaluates the returned trajectory. The expected `path`
compiles to a `PathOrderEvaluator` automatically, then the test's explicit
evaluators run over the same `RunContext`.

The framework ships two ready invokers:
- `scripted_invoker(chain, output=...)` — replays a fixed chain; used in tests
  and wherever the deterministic tier already knows the expected dispatch order.
- `mock_chain_invoker` — builds the trajectory from the test's own `path` +
  `subagent_mocks`, i.e. "assume the orchestrator dispatches exactly the
  declared chain"; a baseline deterministic tier when no planner is wired.

A real consumer supplies its own invoker that actually runs the orchestrator
(mocked subagents for the gate tier, real subprocess for the live tier).
"""

from __future__ import annotations

import statistics
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.model.core.branch_model import BranchTest
from open_agent_compiler.model.core.test_model import (
    AnyEvaluator,
    PathOrderEvaluator,
    SubstringEvaluator,
)
from open_agent_compiler.testing.evaluation import (
    EvaluationResult,
    RunContext,
    ToolCallRecord,
    evaluate,
)


class BranchTrajectory(BaseModel):
    """What an invoker returns: the joint final output + the recorded chain.

    `error` and `blocked_tools` are the tool-discipline signal: a live invoker
    surfaces the opencode session error and the denied/blocked tool attempts
    (``(tool, reason)`` pairs) so the outcome evaluator can forward them to the
    judge + failures, instead of scoring an errored/flailing run on prose alone.
    Both default empty, so existing (gate-tier / scripted) invokers are unchanged.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    output: Any = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    error: str | None = None
    blocked_tools: list[tuple[str, str]] = Field(default_factory=list)


# An invoker drives the branch for a test and returns its trajectory.
BranchInvoker = Callable[[BranchTest], BranchTrajectory]


class BranchRunResult(BaseModel):
    """Outcome of running one BranchTest."""

    model_config = ConfigDict(frozen=False)

    test_name: str
    entry_agent: str
    passed: bool
    score: float
    results: list[EvaluationResult] = Field(default_factory=list)
    chain: list[str] = Field(default_factory=list)


def _evaluators_for(test: BranchTest) -> list[AnyEvaluator]:
    """The path-order check (from `path`) plus the test's explicit evaluators."""
    evaluators: list[AnyEvaluator] = []
    if test.path:
        evaluators.append(
            PathOrderEvaluator(
                name=f"{test.name}:path",
                steps=test.path,
                contiguous=test.contiguous_path,
            )
        )
    evaluators.extend(test.evaluators)
    return evaluators


def _named(result: EvaluationResult, name: str) -> EvaluationResult:
    """Prefix an evaluation's name so step-contract results are attributable."""
    result.evaluator_name = (
        f"{name}:{result.evaluator_name}" if result.evaluator_name else name
    )
    return result


def evaluate_step_contracts(
    test: BranchTest,
    trajectory: BranchTrajectory,
    *,
    judge: Any = None,
) -> list[EvaluationResult]:
    """Per-step contracts: each recorded dispatch of `contract.step` must
    satisfy the contract's input (args) and output evaluators. A required
    step that never appears in the trajectory fails the contract outright."""
    results: list[EvaluationResult] = []
    for contract in test.step_contracts:
        calls = [c for c in trajectory.tool_calls if c.name == contract.step]
        label = f"step:{contract.step}"
        if not calls:
            probe = SubstringEvaluator(name=label, needle=contract.step)
            if contract.required:
                results.append(
                    EvaluationResult.from_check(
                        probe, False,
                        evidence=f"required step {contract.step!r} was never dispatched",
                    )
                )
            else:
                results.append(
                    EvaluationResult.skip(
                        probe, f"step {contract.step!r} not dispatched (optional)",
                    )
                )
            continue
        for index, call in enumerate(calls):
            occ = f"{label}[{index}]" if len(calls) > 1 else label
            in_ctx = RunContext(output=call.args, judge=judge)
            out_ctx = RunContext(output=call.output, judge=judge)
            for ev in contract.input_evaluators:
                results.append(_named(evaluate(ev, in_ctx), f"{occ}:input"))
            for ev in contract.output_evaluators:
                results.append(_named(evaluate(ev, out_ctx), f"{occ}:output"))
    return results


def run_branch_test(
    test: BranchTest,
    invoker: BranchInvoker,
    *,
    judge: Any = None,
) -> BranchRunResult:
    """Drive `test` through `invoker` and evaluate the resulting trajectory."""
    trajectory = invoker(test)
    ctx = RunContext(
        output=trajectory.output,
        tool_calls=list(trajectory.tool_calls),
        judge=judge,
    )
    evaluators = _evaluators_for(test)
    results = [evaluate(ev, ctx) for ev in evaluators]
    results.extend(evaluate_step_contracts(test, trajectory, judge=judge))
    # A branch with no evaluators at all is a misconfiguration, not a pass.
    scored = [r for r in results if not r.skipped]
    passed = bool(results) and all(r.passed for r in results)
    score = statistics.fmean([r.score for r in scored]) if scored else 0.0
    return BranchRunResult(
        test_name=test.name,
        entry_agent=test.entry_agent,
        passed=passed,
        score=score,
        results=results,
        chain=[c.name for c in ctx.tool_calls],
    )


# --- ready-made invokers ----------------------------------------------------

def scripted_invoker(
    chain: list[str | tuple[str, dict[str, Any]]],
    *,
    output: Any = None,
) -> BranchInvoker:
    """Replay a fixed dispatch `chain` (names, or (name, args) pairs).

    Useful in tests and as the deterministic tier when the expected order is
    already known. `output` is the joint final output handed to output-shape
    evaluators.
    """

    def _invoke(_test: BranchTest) -> BranchTrajectory:
        calls: list[ToolCallRecord] = []
        for step in chain:
            if isinstance(step, tuple):
                name, args = step
            else:
                name, args = step, {}
            calls.append(ToolCallRecord(name=name, args=dict(args)))
        return BranchTrajectory(output=output, tool_calls=calls)

    return _invoke


def mock_chain_invoker(test: BranchTest) -> BranchTrajectory:
    """Baseline deterministic tier: assume the orchestrator dispatches exactly
    the test's declared `path`, attaching each step's `subagent_mocks` output as
    that call's output and the LAST step's mock as the joint output.

    This does NOT run a planner — it's the trivial "declared chain happened"
    fixture. Real gating uses a consumer invoker that runs the orchestrator with
    its subagents mocked; this exists so a branch is runnable out of the box.
    """
    calls = [
        ToolCallRecord(name=step, output=test.subagent_mocks.get(step))
        for step in test.path
    ]
    output: Any = None
    if test.path:
        output = test.subagent_mocks.get(test.path[-1])
    return BranchTrajectory(output=output, tool_calls=calls)
