"""Workflow executor — graph walking, retries, events, and the autoloop bridge."""

from __future__ import annotations

from typing import Any

import pytest

from open_agent_compiler.improvement import (
    Criterion,
    NumericFieldMutator,
    OptimisationCriterion,
    Probe,
    optimize_callable,
)
from open_agent_compiler.interactive.events import CollectingSink, EventKind
from open_agent_compiler.model.core.test_model import SubstringEvaluator
from open_agent_compiler.model.core.workflow_model import Gate, GateCheck
from open_agent_compiler.workflow import (
    WorkflowContext,
    WorkflowRoute,
    WorkflowSpec,
    WorkflowStepSpec,
    run_workflow,
    run_workflow_sync,
)


def _spec(start: str, *steps: WorkflowStepSpec, workflow_id: str = "wf") -> WorkflowSpec:
    return WorkflowSpec(workflow_id=workflow_id, start=start, steps=tuple(steps))


# ── linear execution + state passing ───────────────────────────────────


async def test_linear_three_steps_pass_state_along() -> None:
    def first(ctx: WorkflowContext, params: dict) -> dict:
        return {"x": params["base"]}

    def second(ctx: WorkflowContext, params: dict) -> dict:
        return {"y": ctx.get("x") + 1}

    def third(ctx: WorkflowContext, params: dict) -> str:
        return f"sum:{ctx.get('x') + ctx.get('y')}"

    spec = _spec(
        "a",
        WorkflowStepSpec(id="a", runner="first", params={"base": 1}, next="b"),
        WorkflowStepSpec(id="b", runner="second", next="c"),
        WorkflowStepSpec(id="c", runner="third"),
    )
    result = await run_workflow(
        spec, {"first": first, "second": second, "third": third},
    )
    assert result.status == "completed"
    assert result.state["x"] == 1 and result.state["y"] == 2
    # dict returns are merged AND stored under "<id>.output"; scalar too.
    assert result.state["a.output"] == {"x": 1}
    assert result.state["c.output"] == "sum:3"
    assert [(r.step_id, r.status, r.attempt) for r in result.records] == [
        ("a", "ok", 1), ("b", "ok", 1), ("c", "ok", 1),
    ]


async def test_none_return_leaves_state_untouched() -> None:
    spec = _spec("a", WorkflowStepSpec(id="a", runner="quiet"))
    result = await run_workflow(spec, {"quiet": lambda ctx, params: None})
    assert result.status == "completed"
    assert "a.output" not in result.state


# ── route branching ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("temperature", "expected_path"), [(80, "heat"), (10, "chill")],
)
async def test_routes_branch_on_state_first_match_wins(
    temperature: int, expected_path: str,
) -> None:
    def classify(ctx: WorkflowContext, params: dict) -> str:
        return "hot" if ctx.get("temperature") >= 50 else "cold"

    def tag(ctx: WorkflowContext, params: dict) -> dict:
        return {"path": params["label"]}

    spec = _spec(
        "classify",
        WorkflowStepSpec(
            id="classify",
            runner="classify",
            routes=(
                WorkflowRoute(when="classify.output", equals="hot", goto="heat"),
            ),
            next="chill",
        ),
        WorkflowStepSpec(id="heat", runner="tag", params={"label": "heat"}),
        WorkflowStepSpec(id="chill", runner="tag", params={"label": "chill"}),
    )
    result = await run_workflow(
        spec,
        {"classify": classify, "tag": tag},
        initial_state={"temperature": temperature},
    )
    assert result.status == "completed"
    assert result.state["path"] == expected_path
    visited = {r.step_id for r in result.records}
    assert expected_path in visited and len(visited) == 2


# ── gates ──────────────────────────────────────────────────────────────


async def test_gate_all_skips_step_but_next_is_still_followed() -> None:
    gate = Gate(
        logic="all",
        checks=(
            GateCheck(variable="mode", value="fast"),
            GateCheck(variable="ready", value="True"),
        ),
    )
    spec = _spec(
        "guarded",
        WorkflowStepSpec(id="guarded", runner="mark", gate=gate, next="always"),
        WorkflowStepSpec(id="always", runner="mark"),
    )
    calls: list[str] = []

    def mark(ctx: WorkflowContext, params: dict) -> None:
        calls.append("ran")

    result = await run_workflow(
        spec, {"mark": mark}, initial_state={"mode": "fast", "ready": False},
    )
    assert result.status == "completed"
    assert result.records[0].status == "gate_skipped"
    assert result.records[0].attempt == 0
    assert result.records[1].step_id == "always"  # skip still advances
    assert calls == ["ran"]


async def test_gate_any_runs_when_one_check_matches() -> None:
    gate = Gate(
        logic="any",
        checks=(
            GateCheck(variable="mode", value="fast"),
            GateCheck(variable="ready", value="True"),
        ),
    )
    spec = _spec("guarded", WorkflowStepSpec(id="guarded", runner="mark", gate=gate))
    result = await run_workflow(
        spec,
        {"mark": lambda ctx, params: "ran"},
        initial_state={"mode": "slow", "ready": True},
    )
    assert result.records[0].status == "ok"
    assert result.state["guarded.output"] == "ran"


# ── retries / on_error / failure ───────────────────────────────────────


async def test_retry_then_success_records_each_attempt() -> None:
    attempts = {"n": 0}

    def flaky(ctx: WorkflowContext, params: dict) -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient")
        return "recovered"

    spec = _spec("a", WorkflowStepSpec(id="a", runner="flaky", retries=1))
    result = await run_workflow(spec, {"flaky": flaky})
    assert result.status == "completed"
    assert [(r.attempt, r.status) for r in result.records] == [
        (1, "error"), (2, "ok"),
    ]
    assert "transient" in (result.records[0].error or "")
    assert result.state["a.output"] == "recovered"


async def test_retries_exhausted_takes_on_error_path() -> None:
    def broken(ctx: WorkflowContext, params: dict) -> None:
        raise ValueError("always")

    spec = _spec(
        "a",
        WorkflowStepSpec(id="a", runner="broken", retries=1, on_error="cleanup"),
        WorkflowStepSpec(id="cleanup", runner="clean"),
    )
    result = await run_workflow(
        spec, {"broken": broken, "clean": lambda ctx, params: "cleaned"},
    )
    assert result.status == "completed"
    assert result.error is None
    assert [r.status for r in result.records] == ["error", "error", "ok"]
    assert result.state["cleanup.output"] == "cleaned"


async def test_retries_exhausted_without_on_error_fails_the_run() -> None:
    def broken(ctx: WorkflowContext, params: dict) -> None:
        raise ValueError("always broken")

    spec = _spec(
        "a",
        WorkflowStepSpec(id="a", runner="broken", retries=2, next="never"),
        WorkflowStepSpec(id="never", runner="broken"),
    )
    result = await run_workflow(spec, {"broken": broken})
    assert result.status == "failed"
    assert "always broken" in (result.error or "")
    assert "3 attempt(s)" in (result.error or "")
    assert len(result.records) == 3
    assert all(r.step_id == "a" for r in result.records)


async def test_unknown_runner_is_a_step_error() -> None:
    spec = _spec("a", WorkflowStepSpec(id="a", runner="ghost"))
    result = await run_workflow(spec, {})
    assert result.status == "failed"
    assert "unknown runner 'ghost'" in (result.error or "")

    # ...and on_error still applies to it.
    spec2 = _spec(
        "a",
        WorkflowStepSpec(id="a", runner="ghost", on_error="fallback"),
        WorkflowStepSpec(id="fallback", runner="ok"),
    )
    rescued = await run_workflow(spec2, {"ok": lambda ctx, params: "fine"})
    assert rescued.status == "completed"
    assert rescued.state["fallback.output"] == "fine"


# ── cycles / max_steps ─────────────────────────────────────────────────


async def test_cycle_hits_max_steps_and_halts() -> None:
    spec = _spec(
        "a",
        WorkflowStepSpec(id="a", runner="noop", next="b"),
        WorkflowStepSpec(id="b", runner="noop", next="a"),
    )
    result = await run_workflow(
        spec, {"noop": lambda ctx, params: "tick"}, max_steps=5,
    )
    assert result.status == "halted"
    assert "max_steps=5" in (result.error or "")
    assert len(result.records) == 5  # the guard fired before step 6


# ── async + sync runners ───────────────────────────────────────────────


async def test_async_and_sync_runners_mix() -> None:
    async def fetch(ctx: WorkflowContext, params: dict) -> dict:
        return {"data": "payload"}

    def render(ctx: WorkflowContext, params: dict) -> str:
        return f"rendered {ctx.get('data')}"

    spec = _spec(
        "fetch",
        WorkflowStepSpec(id="fetch", runner="fetch", next="render"),
        WorkflowStepSpec(id="render", runner="render"),
    )
    result = await run_workflow(spec, {"fetch": fetch, "render": render})
    assert result.status == "completed"
    assert result.state["render.output"] == "rendered payload"


# ── events ─────────────────────────────────────────────────────────────


async def test_events_arrive_in_order_with_workflow_source() -> None:
    sink = CollectingSink()
    spec = _spec(
        "a",
        WorkflowStepSpec(id="a", runner="noop", next="b"),
        WorkflowStepSpec(id="b", runner="noop"),
        workflow_id="pipeline",
    )
    await run_workflow(spec, {"noop": lambda ctx, params: "x"}, sink=sink)
    assert sink.kinds() == [EventKind.PROGRESS] * 4  # start/end per step
    assert all(e.source == "workflow:pipeline" for e in sink.events)
    assert [e.seq for e in sink.events] == [0, 1, 2, 3]
    assert [(e.payload["step"], e.payload["phase"]) for e in sink.events] == [
        ("a", "start"), ("a", "end"), ("b", "start"), ("b", "end"),
    ]
    assert sink.events[0].payload["current"] == 1
    assert sink.events[2].payload["current"] == 2


async def test_step_failure_emits_tool_error_event() -> None:
    sink = CollectingSink()

    def broken(ctx: WorkflowContext, params: dict) -> None:
        raise RuntimeError("kaput")

    spec = _spec("a", WorkflowStepSpec(id="a", runner="broken", retries=1))
    await run_workflow(spec, {"broken": broken}, sink=sink)
    errors = [e for e in sink.events if e.kind == EventKind.TOOL_ERROR]
    assert [e.payload["attempt"] for e in errors] == [1, 2]
    assert "kaput" in errors[0].payload["error"]


# ── sync wrapper ───────────────────────────────────────────────────────


def test_run_workflow_sync_runs_to_completion() -> None:
    spec = _spec("a", WorkflowStepSpec(id="a", runner="noop"))
    result = run_workflow_sync(spec, {"noop": lambda ctx, params: "done"})
    assert result.status == "completed"
    assert result.state["a.output"] == "done"


async def test_run_workflow_sync_refuses_inside_a_running_loop() -> None:
    spec = _spec("a", WorkflowStepSpec(id="a", runner="noop"))
    with pytest.raises(RuntimeError, match="running event loop"):
        run_workflow_sync(spec, {"noop": lambda ctx, params: None})


# ── autoloop integration ───────────────────────────────────────────────


def test_workflow_spec_is_an_autoresearch_target() -> None:
    """The whole point: a WorkflowSpec.model_dump() is a candidate
    definition the improvement loop can mutate — here a NumericFieldMutator
    lowers a step's threshold param until every probe's final output passes
    a SubstringEvaluator."""
    runners = {
        "threshold_classifier": lambda ctx, params: {
            "verdict": "deliver"
            if ctx.get("signal") >= params["threshold"]
            else "hold",
        },
        "report": lambda ctx, params: f"decision: {ctx.get('verdict')}",
    }
    baseline_spec = _spec(
        "classify",
        WorkflowStepSpec(
            id="classify",
            runner="threshold_classifier",
            params={"threshold": 0.9},  # too strict: probes sit at 0.5/0.7
            next="report",
        ),
        WorkflowStepSpec(id="report", runner="report"),
        workflow_id="signal-pipeline",
    )

    def factory(definition: dict[str, Any]):
        spec = WorkflowSpec.model_validate(definition)

        def execute(payload: Any) -> Any:
            result = run_workflow_sync(
                spec, runners, initial_state=dict(payload),
            )
            return result.state.get("report.output")

        return execute

    probes = [
        Probe(
            probe_id=f"signal-{value}",
            payload={"signal": value},
            evaluators=(SubstringEvaluator(needle="deliver"),),
        )
        for value in (0.5, 0.7)
    ]
    result = optimize_callable(
        component_id="workflow:signal-pipeline",
        baseline_definition=baseline_spec.model_dump(),
        executable_factory=factory,
        probes=probes,
        mutators=[
            NumericFieldMutator("steps.0.params.threshold", scale=0.5, minimum=0.1),
        ],
        criterion=OptimisationCriterion(
            name="delivers",
            criteria=(Criterion(kind="pass_rate", target=1.0, hard=True),),
        ),
        max_rounds=3,
    )
    best = result.best(metric="pass_rate")
    assert best is not None
    assert best.metrics["pass_rate"] == 1.0
    assert best.definition["steps"][0]["params"]["threshold"] <= 0.5
    # The winning definition is still a valid, runnable workflow.
    tuned = WorkflowSpec.model_validate(best.definition)
    rerun = run_workflow_sync(tuned, runners, initial_state={"signal": 0.6})
    assert rerun.state["report.output"] == "decision: deliver"
