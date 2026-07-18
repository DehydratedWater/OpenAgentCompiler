"""Workflow DAG spec — validation, dotted state lookup, runtime gates."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from open_agent_compiler.model.core.workflow_model import Gate, GateCheck
from open_agent_compiler.workflow import (
    MISSING,
    WorkflowContext,
    WorkflowRoute,
    WorkflowSpec,
    WorkflowStepSpec,
    gate_passes,
    get_path,
)


def _step(step_id: str, **kwargs) -> WorkflowStepSpec:
    return WorkflowStepSpec(id=step_id, runner="noop", **kwargs)


# ── spec validation ────────────────────────────────────────────────────


def test_spec_accepts_a_consistent_graph() -> None:
    spec = WorkflowSpec(
        workflow_id="wf",
        start="a",
        steps=(
            _step("a", next="b", on_error="b"),
            _step("b", routes=(WorkflowRoute(when="x", equals=1, goto="a"),)),
        ),
    )
    assert spec.step("b").routes[0].goto == "a"
    with pytest.raises(KeyError):
        spec.step("nope")


def test_spec_rejects_duplicate_step_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate step ids"):
        WorkflowSpec(workflow_id="wf", start="a", steps=(_step("a"), _step("a")))


def test_spec_rejects_missing_start() -> None:
    with pytest.raises(ValidationError, match="start step"):
        WorkflowSpec(workflow_id="wf", start="ghost", steps=(_step("a"),))


def test_spec_rejects_dangling_references() -> None:
    with pytest.raises(ValidationError, match="unknown step 'ghost'"):
        WorkflowSpec(workflow_id="wf", start="a", steps=(_step("a", next="ghost"),))
    with pytest.raises(ValidationError, match="unknown step 'ghost'"):
        WorkflowSpec(
            workflow_id="wf", start="a", steps=(_step("a", on_error="ghost"),),
        )
    with pytest.raises(ValidationError, match="unknown step 'ghost'"):
        WorkflowSpec(
            workflow_id="wf",
            start="a",
            steps=(
                _step("a", routes=(WorkflowRoute(when="x", equals=1, goto="ghost"),)),
            ),
        )


def test_spec_round_trips_through_model_dump() -> None:
    """The autoloop contract: dump → mutate-able plain data → validate."""
    spec = WorkflowSpec(
        workflow_id="wf",
        start="a",
        steps=(
            _step(
                "a",
                params={"threshold": 0.5},
                gate=Gate(checks=(GateCheck(variable="mode", value="on"),)),
                routes=(WorkflowRoute(when="a.output", equals="hot", goto="b"),),
                next="b",
                retries=2,
                on_error="b",
            ),
            _step("b"),
        ),
    )
    assert WorkflowSpec.model_validate(spec.model_dump()) == spec


def test_step_spec_is_frozen() -> None:
    step = _step("a")
    with pytest.raises(ValidationError):
        step.runner = "other"  # type: ignore[misc]


# ── dotted state lookup ────────────────────────────────────────────────


def test_get_path_exact_flat_key_wins_over_dotted_descent() -> None:
    state = {"classify.output": "hot", "classify": {"output": "cold"}}
    assert get_path(state, "classify.output") == "hot"


def test_get_path_dotted_descent_and_list_indexing() -> None:
    state = {"a": {"b": {"c": 3}}, "items": [{"name": "x"}, {"name": "y"}]}
    assert get_path(state, "a.b.c") == 3
    assert get_path(state, "items.1.name") == "y"
    assert get_path(state, "a.b.missing", default="d") == "d"
    assert get_path(state, "items.9.name", default="d") == "d"


def test_get_path_flat_prefix_then_descent() -> None:
    # A step output stored under a flat "id.output" key, addressed deeper.
    state = {"classify.output": {"label": "hot"}}
    assert get_path(state, "classify.output.label") == "hot"


def test_get_path_distinguishes_stored_none_from_absence() -> None:
    state = {"x": None}
    assert get_path(state, "x", default="d") is None
    assert get_path(state, "y", default="d") == "d"
    assert get_path(state, "y", MISSING) is MISSING


# ── runtime gate semantics ─────────────────────────────────────────────


def test_gate_compares_stringified_state_values() -> None:
    gate = Gate(checks=(GateCheck(variable="count", value="5"),))
    assert gate_passes(gate, {"count": 5})
    assert gate_passes(gate, {"count": "5"})
    assert not gate_passes(gate, {"count": 6})


def test_gate_all_and_any_logic() -> None:
    checks = (
        GateCheck(variable="mode", value="fast"),
        GateCheck(variable="ready", value="True"),
    )
    state = {"mode": "fast", "ready": False}
    assert not gate_passes(Gate(logic="all", checks=checks), state)
    assert gate_passes(Gate(logic="any", checks=checks), state)
    state["ready"] = True
    assert gate_passes(Gate(logic="all", checks=checks), state)


def test_gate_missing_variable_fails_its_check() -> None:
    gate = Gate(checks=(GateCheck(variable="absent", value="None"),))
    assert not gate_passes(gate, {})


def test_gate_supports_dotted_variables() -> None:
    gate = Gate(checks=(GateCheck(variable="meta.tier", value="gold"),))
    assert gate_passes(gate, {"meta": {"tier": "gold"}})


# ── context ────────────────────────────────────────────────────────────


def test_workflow_context_get_reads_dotted_paths() -> None:
    ctx = WorkflowContext({"a": {"b": 1}})
    assert ctx.get("a.b") == 1
    assert ctx.get("a.z", default=9) == 9
    # No sink wired → emitting is still safe (NullSink default).
    ctx.emitter.progress("noop")
