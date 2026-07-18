"""Autoresearch — wrap ARBITRARY logic in the improvement loop.

The `IterativeLoop` is already decoupled from how candidates are evaluated,
but until now the only things that could *be* a candidate were compiled
components (agents / tools / skills) because evaluators were hand-wired to
the compile-and-run-opencode path. This module closes the gap the vision
demands ("any logic should be wrapped with autoresearch loops"): any
callable whose behaviour is controlled by a JSON-able definition dict — a
checker cooldown policy, a context-ranking function, a tool-selection
heuristic, a workflow graph — becomes an optimisation target.

Three pieces:

- :class:`Probe` — one test case for the callable: a payload plus the same
  evaluator models the test framework uses everywhere else (substring,
  regex, jsonpath, tool_called, llm_judge, ...). Probes are plain Pydantic
  data, so they can be authored by hand OR generated dynamically from real
  data (the chat corpus, a client spec) — which is what makes the whole
  setup model-portable: switch the local model, regenerate/rerun, done.
- :func:`run_probe` / :func:`run_probes` — execute the callable on each
  probe payload and score the outcome with the standard evaluation
  dispatcher. An exception inside the callable scores 0 and is recorded,
  never propagated — a crashing candidate must lose, not kill the loop.
- :func:`build_callable_evaluator` + :func:`optimize_callable` — adapt the
  above into the `IterativeLoop` evaluator contract. Metric names mirror
  `open_agent_compiler.improvement.branch` (``pass_rate`` / ``score_floor`` / ``score_mean``
  / ``score_floor:by_name:<probe>``) so existing criteria, contract gates
  and snapshot promotion work unchanged.

The candidate *definition* is the unit of mutation. For text fields the
existing prompt mutators apply; for numeric/choice policy knobs see
`open_agent_compiler.improvement.mutators.fields`.
"""

from __future__ import annotations

import statistics
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.loop import Evaluator, IterativeLoop, LoopResult
from open_agent_compiler.improvement.mutators import Mutator
from open_agent_compiler.improvement.version import ComponentRegistry, ComponentVersion
from open_agent_compiler.model.core.test_model import AnyEvaluator
from open_agent_compiler.testing.evaluation import (
    EvaluationResult,
    RunContext,
    ToolCallRecord,
    evaluate,
)

__all__ = [
    "Probe",
    "ProbeOutcome",
    "ProbeRunResult",
    "ProbeExecutable",
    "ExecutableFactory",
    "run_probe",
    "run_probes",
    "build_callable_evaluator",
    "optimize_callable",
]


class Probe(BaseModel):
    """One test case for an arbitrary executable.

    ``payload`` is handed to the executable as-is. ``evaluators`` reuse the
    framework's standard evaluator models so every existing kind (incl.
    ``llm_judge``) scores callables exactly the way it scores agents.
    """

    model_config = ConfigDict(frozen=True)

    probe_id: str
    payload: Any = None
    evaluators: tuple[AnyEvaluator, ...] = ()
    weight: float = Field(default=1.0, gt=0.0)
    notes: str = ""


class ProbeOutcome(BaseModel):
    """What an executable may return when it wants to expose run evidence.

    A bare string (or any other value) is also accepted by :func:`run_probe`
    and treated as ``ProbeOutcome(output=value)``. ``tool_calls`` feed the
    tool_called / path_order evaluators and contract gates; ``extras`` is
    free-form context for judges.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    output: Any = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


# The thing being optimised: payload in, outcome (or any output value) out.
ProbeExecutable = Callable[[Any], Any]
# Builds the executable FROM a candidate's definition dict. This is where a
# consumer turns parameters into behaviour (close over the dict, compile a
# prompt, build a policy object...). It receives a deep copy — mutating it
# can never staleify the stored ComponentVersion.
ExecutableFactory = Callable[[dict[str, Any]], ProbeExecutable]


class ProbeRunResult(BaseModel):
    """Scored outcome of one probe against one executable."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    probe_id: str
    passed: bool
    score: float
    weight: float = 1.0
    evaluations: list[EvaluationResult] = Field(default_factory=list)
    error: str | None = None


def _coerce_outcome(value: Any) -> ProbeOutcome:
    if isinstance(value, ProbeOutcome):
        return value
    return ProbeOutcome(output=value)


def run_probe(
    probe: Probe,
    executable: ProbeExecutable,
    *,
    judge: Any = None,
) -> ProbeRunResult:
    """Execute one probe and score it with the standard dispatcher.

    Scoring: mean of non-skipped evaluator scores; ``passed`` requires every
    non-skipped evaluator to pass. A probe with no (applicable) evaluators
    scores 1.0 when the executable ran cleanly — an existence probe. An
    exception in the executable scores 0 with the error recorded.
    """
    try:
        outcome = _coerce_outcome(executable(probe.payload))
    except Exception as exc:  # noqa: BLE001 — candidate failure is data, not a crash
        return ProbeRunResult(
            probe_id=probe.probe_id,
            passed=False,
            score=0.0,
            weight=probe.weight,
            error=f"{type(exc).__name__}: {exc}",
        )

    ctx = RunContext(
        output=outcome.output,
        tool_calls=outcome.tool_calls,
        judge=judge,
        extras=outcome.extras,
    )
    evaluations = [evaluate(e, ctx) for e in probe.evaluators]
    considered = [e for e in evaluations if not e.skipped]
    if considered:
        score = statistics.fmean(e.score for e in considered)
        passed = all(e.passed for e in considered)
    else:
        score, passed = 1.0, True
    return ProbeRunResult(
        probe_id=probe.probe_id,
        passed=passed,
        score=score,
        weight=probe.weight,
        evaluations=evaluations,
    )


def run_probes(
    probes: list[Probe],
    executable: ProbeExecutable,
    *,
    judge: Any = None,
) -> list[ProbeRunResult]:
    return [run_probe(p, executable, judge=judge) for p in probes]


def metrics_from_results(results: list[ProbeRunResult]) -> dict[str, float]:
    """Aggregate probe results into the loop's standard metric shape.

    Mirrors `open_agent_compiler.improvement.branch.build_branch_evaluator` so criteria,
    contract gates, charts and promotion treat callables and branches alike.
    ``score_mean`` is probe-weight weighted; ``pass_rate``/``score_floor``
    are unweighted (a low-weight probe still gates the floor — weights
    express *emphasis*, not permission to fail).
    """
    if not results:
        return {}
    total_weight = sum(r.weight for r in results)
    metrics: dict[str, float] = {
        "pass_rate": sum(1 for r in results if r.passed) / len(results),
        "score_floor": min(r.score for r in results),
        "score_mean": sum(r.score * r.weight for r in results) / total_weight,
    }
    for r in results:
        metrics[f"score_floor:by_name:{r.probe_id}"] = r.score
    return metrics


def build_callable_evaluator(
    probes: list[Probe],
    executable_factory: ExecutableFactory,
    *,
    judge: Any = None,
) -> Evaluator:
    """An `IterativeLoop` evaluator that scores a candidate definition by
    rebuilding its executable and running every probe against it."""

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        executable = executable_factory(version.definition_copy())
        return metrics_from_results(run_probes(probes, executable, judge=judge))

    return evaluator


def optimize_callable(
    *,
    component_id: str,
    baseline_definition: dict[str, Any],
    executable_factory: ExecutableFactory,
    probes: list[Probe],
    mutators: list[Mutator],
    criterion: OptimisationCriterion,
    judge: Any = None,
    kind: str = "prompt",
    registry: ComponentRegistry | None = None,
    max_rounds: int = 3,
    frontier_size: int = 3,
) -> LoopResult:
    """Wrap arbitrary logic in a full autoresearch loop, one call.

    ``baseline_definition`` is the JSON-able parameter dict the factory
    turns into behaviour. Everything downstream (criteria, hard gates,
    snapshot promotion via the returned versions) is the standard pipeline.
    """
    baseline = ComponentVersion.of(component_id, kind, baseline_definition)  # type: ignore[arg-type]
    loop = IterativeLoop(
        baseline=baseline,
        mutators=mutators,
        criterion=criterion,
        evaluator=build_callable_evaluator(
            probes, executable_factory, judge=judge,
        ),
        registry=registry or ComponentRegistry(),
        max_rounds=max_rounds,
        frontier_size=frontier_size,
    )
    return loop.run()
