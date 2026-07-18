"""Contract gate — make the autoloop optimise the REAL goal, not a text proxy.

The lesson (docs/lessons/optimize-the-real-goal-not-text-correctness.md): a
consumer judged candidates on their assistant TEXT, but production delivery
required calling a specific tool (``emit_guidance.py``) whose output is what the
user actually sees — the assistant prose is invisible. Because the loop scored a
TEXT PROXY that diverged from the real delivery contract, the teacher's rewrites
"improved" the text while silently dropping the load-bearing tool-call. Optimised
agents scored great in the loop and delivered NOTHING in production.

This module gives an evaluator a way to GATE on the production contract: wrap any
base evaluator so a candidate that did NOT satisfy the contract over its run
trajectory/artifacts is forced to **score 0** (and the failure reason is
recorded), no matter how good its text is. A beautiful-but-undelivered answer is
a failure.

It reuses the framework's existing trajectory structures — ``ToolCallRecord``
(``RunContext.tool_calls`` / ``BranchTrajectory.tool_calls``) and the
``subagent_dispatch_chain`` parse helper — so the predicate inspects the same run
evidence everything else does. The gate is evaluator-shape agnostic: it works for
the per-agent ``Evaluator`` (``ComponentVersion -> metrics``) AND for any
callable that scores a single run, as long as you can hand it the run trajectory.

Typical use::

    from open_agent_compiler.improvement import (
        contract_gate, require_tool_called, RunOutcome,
    )

    base = build_session_judge_evaluator(...)          # judges DELIVERED payload
    gated = contract_gate(
        base,
        contract=require_tool_called("emit_guidance"),
        outcome_for=lambda version: run_and_capture(version),  # -> RunOutcome
        gated_metrics=("score_floor", "score_floor:by_evaluator:llm_judge",
                       "score_mean", "pass_rate"),
    )

The base evaluator still runs (so the judge keeps grading the *quality* of the
delivered payload); the gate only zeroes the metrics when the contract is unmet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from open_agent_compiler.improvement.loop import Evaluator
from open_agent_compiler.improvement.opencode_eval import subagent_dispatch_chain
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.testing.evaluation import ToolCallRecord

__all__ = [
    "RunOutcome",
    "ContractResult",
    "ContractPredicate",
    "require_tool_called",
    "require_any_tool_called",
    "require_artifact",
    "require_subagent_dispatched",
    "all_of",
    "contract_gate",
    "require_outcome",
]


@dataclass
class RunOutcome:
    """The run evidence a contract predicate inspects.

    A thin, framework-native view over one candidate's run so a predicate can
    check the REAL goal without re-parsing raw opencode output. Populate whatever
    you have — every field is optional and a predicate ignores what it doesn't
    need:

    - ``tool_calls``  — observed ``ToolCallRecord``s (``RunContext.tool_calls`` /
      ``BranchTrajectory.tool_calls``). The primary "did the required tool fire"
      signal.
    - ``dispatch_chain`` — orchestrator sub-agent names (from
      ``subagent_dispatch_chain``); for "did it delegate to the delivery agent".
    - ``artifacts`` — emitted deliverables keyed by name (e.g. the payload the
      required tool wrote). For "was the deliverable produced".
    - ``stdout`` — the raw opencode event stream, so a predicate can fall back to
      ``subagent_dispatch_chain(stdout)`` when no structured chain is supplied.
    - ``output`` — the assistant text. Present for completeness; the WHOLE point
      of this module is that the contract must NOT be judged on this alone.
    """

    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    dispatch_chain: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    output: Any = None

    @classmethod
    def from_run_result(cls, result: Any, *, output: Any = None) -> "RunOutcome":
        """Build a RunOutcome from an ``OpencodeRunResult`` (or a fake of one).

        Pulls the sub-agent dispatch chain off the result (real results expose
        ``subagent_dispatch_chain()``; we also keep ``stdout`` so a predicate can
        re-parse). ``output`` defaults to ``result.final_text()`` when available.
        """
        chain: list[str] = []
        fn = getattr(result, "subagent_dispatch_chain", None)
        if callable(fn):
            try:
                chain = [name for name, _ in (fn() or [])]
            except Exception:  # noqa: BLE001
                chain = []
        stdout = str(getattr(result, "stdout", "") or "")
        if output is None:
            ft = getattr(result, "final_text", None)
            if callable(ft):
                try:
                    output = ft()
                except Exception:  # noqa: BLE001
                    output = None
        return cls(dispatch_chain=chain, stdout=stdout, output=output)

    def tool_names(self) -> list[str]:
        """Names of every tool the candidate actually called this run."""
        return [c.name for c in self.tool_calls]

    def all_dispatched(self) -> list[str]:
        """The dispatch chain, falling back to parsing ``stdout`` when empty."""
        if self.dispatch_chain:
            return list(self.dispatch_chain)
        if self.stdout:
            return [name for name, _ in subagent_dispatch_chain(self.stdout)]
        return []


@dataclass
class ContractResult:
    """Verdict of a contract predicate over a RunOutcome."""

    satisfied: bool
    reason: str = ""


# A contract predicate inspects the run evidence and says whether the
# production contract was honoured. Keep them pure + dependency-free.
ContractPredicate = Callable[[RunOutcome], ContractResult]


# --- ready-made predicates --------------------------------------------------


def require_tool_called(tool_name: str) -> ContractPredicate:
    """The candidate MUST have called ``tool_name`` (the delivery tool).

    This is the canonical fix for a failure observed in a production
    chat-assistant deployment: delivery happens via
    ``emit_guidance.py``; assistant text is invisible. ``require_tool_called(
    "emit_guidance")`` matches by substring on the observed tool names (so
    ``emit_guidance``, ``python scripts/emit_guidance.py`` etc. all count).
    """

    def predicate(run: RunOutcome) -> ContractResult:
        names = run.tool_names()
        if any(tool_name in n for n in names):
            return ContractResult(True, f"required tool {tool_name!r} was called")
        return ContractResult(
            False,
            f"CONTRACT BROKEN: required delivery tool {tool_name!r} was NOT called "
            f"(observed tools: {names or '[]'}). The answer was not delivered.",
        )

    return predicate


def require_any_tool_called(tool_names: list[str]) -> ContractPredicate:
    """At least one of ``tool_names`` must have been called (any delivery path)."""

    def predicate(run: RunOutcome) -> ContractResult:
        called = run.tool_names()
        for want in tool_names:
            if any(want in n for n in called):
                return ContractResult(True, f"delivery tool {want!r} was called")
        return ContractResult(
            False,
            f"CONTRACT BROKEN: none of the required delivery tools {tool_names} "
            f"were called (observed: {called or '[]'}).",
        )

    return predicate


def require_artifact(
    name: str, *, predicate: Callable[[Any], bool] | None = None,
) -> ContractPredicate:
    """A deliverable artifact named ``name`` must have been emitted.

    Optionally pass a ``predicate`` to also check the artifact's CONTENT
    (e.g. non-empty payload). The point: grade the real deliverable, not prose.
    """

    def check(run: RunOutcome) -> ContractResult:
        if name not in run.artifacts:
            return ContractResult(
                False,
                f"CONTRACT BROKEN: deliverable artifact {name!r} was not emitted "
                f"(emitted: {sorted(run.artifacts)}).",
            )
        if predicate is not None and not predicate(run.artifacts[name]):
            return ContractResult(
                False,
                f"CONTRACT BROKEN: deliverable artifact {name!r} was emitted but "
                "failed its content check (e.g. empty / malformed payload).",
            )
        return ContractResult(True, f"deliverable artifact {name!r} was emitted")

    return check


def require_subagent_dispatched(agent_name: str) -> ContractPredicate:
    """An orchestrator MUST have dispatched the delivery sub-agent.

    For multi-step systems where the load-bearing contract is "route to the agent
    that actually delivers", not "produce a nice summary yourself". Matches by
    substring against the dispatch chain (parsed from stdout when not supplied).
    """

    def predicate(run: RunOutcome) -> ContractResult:
        chain = run.all_dispatched()
        if any(agent_name in n for n in chain):
            return ContractResult(True, f"sub-agent {agent_name!r} was dispatched")
        return ContractResult(
            False,
            f"CONTRACT BROKEN: required delivery sub-agent {agent_name!r} was NOT "
            f"dispatched (chain: {chain or '[]'}).",
        )

    return predicate


def all_of(*predicates: ContractPredicate) -> ContractPredicate:
    """Compose predicates — ALL must hold (the conjunction of contracts)."""

    def predicate(run: RunOutcome) -> ContractResult:
        reasons: list[str] = []
        for p in predicates:
            res = p(run)
            if not res.satisfied:
                return res
            reasons.append(res.reason)
        return ContractResult(True, "; ".join(reasons))

    return predicate


# --- the gate ---------------------------------------------------------------


def contract_gate(
    base_evaluator: Evaluator,
    *,
    contract: ContractPredicate,
    outcome_for: Callable[[ComponentVersion], RunOutcome],
    gated_metrics: tuple[str, ...] | None = None,
    failure_metric: str = "contract_satisfied",
    failures_sink: list[dict[str, Any]] | None = None,
) -> Evaluator:
    """Wrap a per-agent ``Evaluator`` so it OPTIMISES THE REAL GOAL.

    Runs ``base_evaluator(version)`` to get the quality metrics (so the judge
    still grades the quality of the DELIVERED payload), then checks the
    production ``contract`` against the candidate's run (``outcome_for(version)``).
    When the contract is NOT satisfied:

    - every score-shaped metric in ``gated_metrics`` is forced to ``0.0`` — a
      beautiful-but-undelivered candidate cannot win;
    - ``failure_metric`` (default ``"contract_satisfied"``) is set to ``0.0``
      (``1.0`` when satisfied) so a HARD criterion can gate on it directly;
    - the failure reason is appended to ``failures_sink`` (when supplied) so the
      teacher's next rewrite is told it dropped a load-bearing contract.

    ``gated_metrics`` defaults to the score-shaped keys the framework's
    evaluators emit (``score_floor``, ``score_mean``, ``pass_rate``, and the
    per-client judge key). Pass an explicit tuple to gate a custom metric set.

    The contract check is the gate; the base evaluator is the quality grade. They
    compose: the loop keeps ranking on the same metrics, but a candidate only
    gets a non-zero score once it actually delivers.
    """
    keys = gated_metrics or (
        "score_floor",
        "score_mean",
        "pass_rate",
        "score_floor:by_evaluator:llm_judge",
    )

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        metrics = dict(base_evaluator(version))
        run = outcome_for(version)
        verdict = contract(run)
        metrics[failure_metric] = 1.0 if verdict.satisfied else 0.0
        if not verdict.satisfied:
            for k in keys:
                if k in metrics:
                    metrics[k] = 0.0
                else:
                    # Ensure the gated score-floor exists even if the base
                    # evaluator never emitted it, so a ranker can't read a
                    # missing (neutral) metric and rank an undelivered candidate.
                    metrics[k] = 0.0
            if failures_sink is not None:
                failures_sink.append({
                    "contract": failure_metric,
                    "reason": verdict.reason,
                    "tool_calls": run.tool_names(),
                    "dispatch_chain": run.all_dispatched()[:8],
                    "artifacts": sorted(run.artifacts),
                    "got_output": str(run.output or "")[:400],
                })
        return metrics

    return evaluator


def require_outcome(
    base_evaluator: Evaluator,
    *,
    contract: ContractPredicate,
    outcome_for: Callable[[ComponentVersion], RunOutcome],
    **kwargs: Any,
) -> Evaluator:
    """Readability alias for :func:`contract_gate`.

    ``require_outcome(base, contract=..., outcome_for=...)`` reads as "this
    evaluator REQUIRES the real outcome", which is the intent at call sites that
    care more about the contract than the wrapping mechanics.
    """
    return contract_gate(
        base_evaluator, contract=contract, outcome_for=outcome_for, **kwargs,
    )
