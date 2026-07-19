"""Interactive-tier evaluator — make the realtime runner an autoloop target.

Closes the last gap in "define once, adapt everywhere": the improvement
loop could evaluate candidates on compiled harnesses (opencode / pi /
codex via harness_eval) but never on the *interactive tier* — yet
`render_interactive_prompt` strips worker scaffolding, so a prompt tuned
against a compiled harness is judged on a rendering the realtime agent
never sees. This module scores candidates by actually running them
through `run_interactive` (the same in-process loop the LangChain /
PydanticAI bindings sit next to), so "interactive" becomes one more
`OptimizationTarget` in `run_per_target_loops`.

Built as a thin adapter over autoresearch: each probe's payload is the
user prompt (or message list), the executable rebuilds the candidate's
`InteractiveAgentSpec` and runs one interactive turn, and the outcome
carries both the final text AND the ToolCallRecords — so the standard
evaluators (substring, tool_called, llm_judge, …) and the loop's
metric shape (pass_rate / score_floor / score_mean) apply unchanged.

The consumer supplies a `SpecFactory` (candidate definition dict →
InteractiveAgentSpec), mirroring branch.py's invoker_factory: rebuild
the AgentDefinition from the mutated dict, call build_interactive_spec
with the live profile. A `client` override (any ChatClient) makes the
whole loop runnable offline against a scripted model — the same
mock-gate/live-promote tiering as every other evaluator.

Typical wiring:

    def spec_factory(defn: dict) -> InteractiveAgentSpec:
        agent = baseline_agent.model_copy(
            update={"system_prompt": defn["system_prompt"]})
        return build_interactive_spec(agent=agent, live_profile=LIVE)

    evaluator = build_interactive_evaluator(
        probes=[Probe(probe_id="greets", payload="say hi",
                      evaluators=(LLMJudgeEvaluator(criteria="friendly"),))],
        spec_factory=spec_factory,
        tool_runner=my_runner, judge=my_judge,
    )
    # → hand to IterativeLoop, or as the "interactive" branch of a
    #   run_per_target_loops evaluator_factory.
"""

from __future__ import annotations

from typing import Any, Callable

from open_agent_compiler.improvement.autoresearch import (
    Probe,
    ProbeOutcome,
    build_callable_evaluator,
    metrics_from_results,
    run_probes,
)
from open_agent_compiler.improvement.loop import Evaluator
from open_agent_compiler.interactive.runner import RunResult, run_interactive
from open_agent_compiler.interactive.spec import InteractiveAgentSpec

# Candidate definition dict → the spec to run it as. The consumer owns
# the merge (which mutated fields apply, which live profile binds) —
# mirrors branch.py's BranchInvokerFactory.
SpecFactory = Callable[[dict[str, Any]], InteractiveAgentSpec]


def outcome_from_run(result: RunResult) -> ProbeOutcome:
    """Map a RunResult onto the probe-outcome shape the evaluators score.

    `output` is the final text; `tool_calls` feed tool_called /
    path_order evaluators; `extras` exposes rounds/error/structured for
    judges and custom evaluators. A run that *errored* (provider
    failure, tool-round cap, structured-parse failure) keeps its error
    visible in extras — and `interactive_probe_executable` raises on
    hard errors so the probe scores 0 rather than judging partial text.
    """
    return ProbeOutcome(
        output=result.output_text,
        tool_calls=list(result.tool_calls),
        extras={
            "rounds": result.rounds,
            "error": result.error,
            "structured": result.structured,
        },
    )


def interactive_probe_executable(
    spec: InteractiveAgentSpec,
    *,
    tool_runner: Callable[..., str] | None = None,
    client: Any = None,
    max_tool_rounds: int = 8,
    fail_on_error: bool = True,
) -> Callable[[Any], ProbeOutcome]:
    """One candidate spec → a ProbeExecutable running interactive turns.

    The probe payload is the user input: a plain string or a
    `{"user_input": ..., "history": [...]}` dict when a probe needs
    prior context. With `fail_on_error` (default), a run whose
    RunResult carries an error raises — autoresearch records the probe
    as failed (score 0) instead of letting a judge grade a broken
    turn's partial text as if it were an answer.
    """

    def _execute(payload: Any) -> ProbeOutcome:
        history = None
        user_input = payload
        if isinstance(payload, dict) and "user_input" in payload:
            user_input = payload["user_input"]
            history = payload.get("history")
        result = run_interactive(
            spec, user_input,
            tool_runner=tool_runner, client=client,
            max_tool_rounds=max_tool_rounds, history=history,
        )
        if fail_on_error and result.error:
            raise RuntimeError(f"interactive run failed: {result.error}")
        return outcome_from_run(result)

    return _execute


def build_interactive_evaluator(
    probes: list[Probe],
    spec_factory: SpecFactory,
    *,
    tool_runner: Callable[..., str] | None = None,
    client: Any = None,
    judge: Any = None,
    max_tool_rounds: int = 8,
    fail_on_error: bool = True,
) -> Evaluator:
    """An IterativeLoop evaluator that scores candidates on the realtime tier.

    For each candidate: rebuild its InteractiveAgentSpec via
    `spec_factory`, run every probe through `run_interactive`, and score
    outcomes with the standard evaluation dispatcher (`judge` powers any
    `llm_judge` evaluators on the probes). Metric names mirror branch /
    autoresearch (`pass_rate` / `score_floor` / `score_mean` /
    `score_floor:by_name:<probe>`), so criteria, contract gates, charts
    and per-target snapshot promotion work unchanged.

    Pass a scripted `client` (any ChatClient) for the offline gate tier;
    omit it to evaluate against the spec's live provider for promotion.
    """

    def factory(defn: dict[str, Any]):
        return interactive_probe_executable(
            spec_factory(defn),
            tool_runner=tool_runner, client=client,
            max_tool_rounds=max_tool_rounds, fail_on_error=fail_on_error,
        )

    return build_callable_evaluator(probes, factory, judge=judge)


def score_interactive_spec(
    spec: InteractiveAgentSpec,
    probes: list[Probe],
    *,
    tool_runner: Callable[..., str] | None = None,
    client: Any = None,
    judge: Any = None,
    max_tool_rounds: int = 8,
) -> dict[str, float]:
    """Score ONE spec against probes — the benchmark half without a loop.

    Useful for regression benchmarks in CI (assert the promoted
    interactive variant still clears its floor) and for comparing tier
    renderings side by side.
    """
    executable = interactive_probe_executable(
        spec, tool_runner=tool_runner, client=client,
        max_tool_rounds=max_tool_rounds,
    )
    return metrics_from_results(run_probes(probes, executable, judge=judge))
