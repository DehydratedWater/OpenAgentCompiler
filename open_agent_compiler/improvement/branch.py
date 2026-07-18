"""Branch optimisation — tune an orchestrator's routing against its branch tests.

The branch *test* primitive (open_agent_compiler/testing/branch.py) asserts an orchestrator
chains the right subagents/tools in the right order. This module makes that
chain an OPTIMISATION target: it drops a branch's tests into the generic
`IterativeLoop` so the same prompt mutators that improve a leaf agent can
improve an orchestrator's routing.

No new loop or mutator is needed. The optimisable component is the entry
(orchestrator) agent itself — `kind="agent"`, so every existing prompt mutator
applies — and the only new piece is the *evaluator*: it reconstructs an invoker
from each candidate's definition and scores it by running the branch tests.

The component id is namespaced `branch:<entry_agent>` so a branch loop and the
entry agent's own per-agent loop coexist in one registry without colliding.

Tiering (the project's both-tier decision) lives in the `invoker_factory` the
consumer supplies: for the gate tier it returns a mock-subagent invoker that
reflects the candidate prompt's routing; for promotion it returns a live
`opencode` invoker. The framework stays tier-agnostic.
"""

from __future__ import annotations

import statistics
from typing import Any, Callable

from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.loop import Evaluator, IterativeLoop
from open_agent_compiler.improvement.opencode_eval import flailing_note
from open_agent_compiler.improvement.mutators import Mutator, MutationContext
from open_agent_compiler.improvement.version import ComponentRegistry, ComponentVersion
from open_agent_compiler.model.core.branch_model import BranchTest
from open_agent_compiler.testing.branch import BranchInvoker, run_branch_test
from open_agent_compiler.testing.evaluation import RunContext, evaluate

# Given a candidate orchestrator definition (the mutated dict), return an
# invoker that drives the branch under THAT definition. This is where the
# consumer reflects prompt changes (live tier) or simulates routing (gate tier).
BranchInvokerFactory = Callable[[dict[str, Any]], BranchInvoker]


def branch_component_id(entry_agent: str) -> str:
    """Namespaced id so a branch loop doesn't collide with the leaf-agent loop."""
    return f"branch:{entry_agent}"


def build_branch_evaluator(
    tests: list[BranchTest],
    invoker_factory: BranchInvokerFactory,
    *,
    judge: Any = None,
) -> Evaluator:
    """An `IterativeLoop` evaluator that scores a candidate by its branch tests.

    Emits:
    - ``pass_rate``  — fraction of branch tests that fully passed;
    - ``score_floor``— worst single branch-test score (the weakest path);
    - ``score_mean`` — mean branch-test score;
    - ``score_floor:by_name:<test>`` — per-test score, for `by_name` criteria.
    """

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        # Deep copy: never let an invoker mutate the version's stored definition
        # (see build_outcome_branch_evaluator) — that staleifies content_hash.
        invoker = invoker_factory(version.definition_copy())
        results = [run_branch_test(t, invoker, judge=judge) for t in tests]
        if not results:
            return {}
        scores = [r.score for r in results]
        passed = sum(1 for r in results if r.passed)
        metrics: dict[str, float] = {
            "pass_rate": passed / len(results),
            "score_floor": min(scores),
            "score_mean": statistics.fmean(scores),
        }
        for r in results:
            metrics[f"score_floor:by_name:{r.test_name}"] = r.score
        return metrics

    return evaluator


# --- non-single-shot (outcome-judged) branch evaluation ---------------------
# This is the DOCUMENTED DEFAULT for orchestrators (the v4 field-report lesson):
# an orchestrator's job is a multi-step session that may spawn sub-agents, so a
# one-turn / hard-path-match test under-scores it. Run it as a FULL session and
# judge the OUTCOME — did the final response fulfil the request — with the
# expected dispatch path offered to the judge as a SOFT HINT only (orchestrators
# frequently do the work themselves rather than dispatch the documented chain,
# which is fine). When the agent acts only via dispatch/tools with no prose, the
# judge is shown the trajectory so it grades the actions.


def make_branch_outcome_judge_test(test: BranchTest, *, pass_threshold: float = 0.7):
    """Build a graded, NON-path-matching outcome `AgentTest` for a branch.

    Returns an AgentTest whose single LLMJudgeEvaluator scores 0..1 how well the
    orchestrator's FINAL response accomplishes the request. The expected `path`
    (if any) is woven into the rubric as a *soft hint*, never a hard match.
    """
    from open_agent_compiler.model.core.test_model import AgentTest, LLMJudgeEvaluator

    task = test.prompt or (test.turns[0].prompt if test.turns else "") or test.name
    path = " -> ".join(test.path) if test.path else ""
    criteria = (
        f'An ORCHESTRATOR agent received this request: "{task}".\n'
        "Score 0..1 how well its FINAL RESPONSE accomplishes that request for the"
        " user — a complete, on-task, useful result. The agent may EITHER do the"
        " work itself OR delegate to sub-agents"
        + (f" (a reasonable plan would involve: {path})" if path else "")
        + "; both are fine as long as the request is fulfilled. Score 0 if it"
        " refuses, stalls, loops, errors out, or returns nothing usable.\n"
        "TOOL DISCIPLINE: if the response includes a 'TOOL DISCIPLINE' note that the"
        " agent made DENIED/blocked tool attempts (forbidden by its allow-list) or"
        " that the session ERRORED, lower the score in proportion to the number of"
        " blocked attempts, and score an errored session as a failed run."
    )
    return AgentTest(
        name=f"{test.name}::outcome",
        prompt=task,
        evaluators=(LLMJudgeEvaluator(
            name="branch-outcome", criteria=criteria, pass_threshold=pass_threshold,
        ),),
    )


def build_outcome_branch_evaluator(
    tests: list[BranchTest],
    invoker_factory: BranchInvokerFactory,
    *,
    judge: Any = None,
    failures_sink: list[dict[str, Any]] | None = None,
    pass_threshold: float = 0.7,
) -> Evaluator:
    """Outcome-judged branch evaluator — the orchestrator default.

    Runs each branch as a full session (via the invoker) and judges the final
    OUTCOME with `make_branch_outcome_judge_test` (no hard path-match). When the
    orchestrator produced no prose but did dispatch/act, the judge is shown the
    trajectory so it grades the actions, not an empty turn.

    Emits ``pass_rate`` + ``score_floor`` + ``score_mean`` (so the same criteria
    used elsewhere apply). When `failures_sink` is given, per-branch evidence for
    every sub-perfect check is appended (cleared each run) for the LLM rewriter.
    """

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        if failures_sink is not None:
            failures_sink.clear()
        if not tests:
            return {"pass_rate": 1.0, "score_floor": 1.0, "score_mean": 1.0}
        # Hand the invoker a deep copy: a live invoker compiles the candidate
        # from this dict and may mutate it (or its nested objects) in place;
        # mutating the version's stored definition would staleify its frozen
        # content_hash and throw at snapshot/promote-write time.
        invoke = invoker_factory(version.definition_copy())
        passes = 0
        scores: list[float] = []
        for bt in tests:
            jt = make_branch_outcome_judge_test(bt, pass_threshold=pass_threshold)
            traj = invoke(bt)
            output = traj.output
            chain = [c.name for c in (traj.tool_calls or [])]
            if not str(output or "").strip() and chain:
                output = (
                    "[orchestrator produced no prose; it acted via: "
                    + " -> ".join(chain) + "]"
                )
            # TOOL-DISCIPLINE signal: forward the session error + denied/blocked
            # tool attempts to the judge (so the rubric's flailing clause fires and
            # an errored run is labelled, not a silent blank) AND to failures (so
            # the rewriter learns to avoid those tools — even if the score passes).
            blocked = list(getattr(traj, "blocked_tools", None) or [])
            err = getattr(traj, "error", None)
            note = flailing_note(blocked, err)
            judged = (str(output or "") + "\n\n" + note).strip() if note else output
            ctx = RunContext(
                output=judged, tool_calls=list(traj.tool_calls or []), judge=judge,
            )
            results = [evaluate(e, ctx) for e in jt.evaluators]
            ok = all(r.passed for r in results) if results else True
            passes += 1 if ok else 0
            scores.append(
                statistics.fmean([r.score for r in results]) if results else 1.0
            )
            if failures_sink is not None:
                for e, r in zip(jt.evaluators, results):
                    if not r.passed or r.score < 1.0 or blocked or err:
                        failures_sink.append({
                            "test": jt.name,
                            "criterion": getattr(e, "criteria", None),
                            "score": round(r.score, 2),
                            "dispatch_chain": chain[:8],
                            "got_output": str(judged)[:400],
                            "judge_reasoning": r.evidence[:250],
                            "blocked_tools": [n for n, _ in blocked],
                            "blocked_attempts": len(blocked),
                            "error": str(err)[:300] if err else None,
                        })
        return {
            "pass_rate": passes / len(tests),
            "score_floor": min(scores) if scores else 1.0,
            "score_mean": statistics.fmean(scores) if scores else 1.0,
        }

    return evaluator


def build_outcome_branch_loop(
    *,
    entry_agent: str,
    entry_definition: Any,
    tests: list[BranchTest],
    invoker_factory: BranchInvokerFactory,
    mutators: list[Mutator],
    criterion: OptimisationCriterion,
    judge: Any = None,
    failures_sink: list[dict[str, Any]] | None = None,
    registry: ComponentRegistry | None = None,
    max_rounds: int = 3,
    frontier_size: int = 3,
    mutation_context: MutationContext | None = None,
    pass_threshold: float = 0.7,
) -> IterativeLoop:
    """Wire an `IterativeLoop` that optimises one orchestrator by OUTCOME.

    The non-single-shot counterpart to `build_branch_loop`: use this for
    orchestrators / multi-step agents (the documented default). `build_branch_loop`
    remains for path-match grading where the exact dispatch chain IS the contract.
    """
    baseline = ComponentVersion.of(
        component_id=branch_component_id(entry_agent),
        kind="agent",
        definition=entry_definition,
    )
    evaluator = build_outcome_branch_evaluator(
        tests, invoker_factory, judge=judge,
        failures_sink=failures_sink, pass_threshold=pass_threshold,
    )
    return IterativeLoop(
        baseline=baseline,
        mutators=mutators,
        criterion=criterion,
        evaluator=evaluator,
        registry=registry or ComponentRegistry(),
        max_rounds=max_rounds,
        frontier_size=frontier_size,
        mutation_context=mutation_context,
    )


def build_branch_loop(
    *,
    entry_agent: str,
    entry_definition: Any,
    tests: list[BranchTest],
    invoker_factory: BranchInvokerFactory,
    mutators: list[Mutator],
    criterion: OptimisationCriterion,
    judge: Any = None,
    registry: ComponentRegistry | None = None,
    max_rounds: int = 3,
    frontier_size: int = 3,
    mutation_context: MutationContext | None = None,
) -> IterativeLoop:
    """Wire a ready-to-run `IterativeLoop` that optimises one branch.

    `entry_definition` is the orchestrator's `AgentDefinition` (or its dump);
    its `system_prompt` is what the prompt mutators rewrite. Run it and read
    `result.winners` exactly like a per-agent loop.
    """
    baseline = ComponentVersion.of(
        component_id=branch_component_id(entry_agent),
        kind="agent",
        definition=entry_definition,
    )
    evaluator = build_branch_evaluator(tests, invoker_factory, judge=judge)
    return IterativeLoop(
        baseline=baseline,
        mutators=mutators,
        criterion=criterion,
        evaluator=evaluator,
        registry=registry or ComponentRegistry(),
        max_rounds=max_rounds,
        frontier_size=frontier_size,
        mutation_context=mutation_context,
    )


__all__ = [
    "BranchInvokerFactory",
    "branch_component_id",
    "build_branch_evaluator",
    "build_branch_loop",
    "make_branch_outcome_judge_test",
    "build_outcome_branch_evaluator",
    "build_outcome_branch_loop",
]
