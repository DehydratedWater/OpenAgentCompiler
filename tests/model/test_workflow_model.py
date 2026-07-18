"""WorkflowStepDefinition + supporting models (Gate, Criterion, Route, ToolUse)."""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.workflow_model import (
    Criterion,
    Gate,
    GateCheck,
    Route,
    ToolUse,
    WorkflowStepDefinition,
)


def test_gate_requires_at_least_one_check() -> None:
    with pytest.raises(ValueError, match="at least one"):
        Gate(checks=())


def test_gate_with_single_check() -> None:
    g = Gate(checks=(GateCheck(variable="kind", value="urgent"),))
    assert g.logic == "all"
    assert len(g.checks) == 1


def test_gate_with_multiple_checks_and_any_logic() -> None:
    g = Gate(
        logic="any",
        checks=(
            GateCheck(variable="kind", value="urgent"),
            GateCheck(variable="vip", value="true"),
        ),
    )
    assert g.logic == "any"
    assert len(g.checks) == 2


def test_criterion_optional_possible_values() -> None:
    c = Criterion(name="severity", question="how bad?")
    assert c.possible_values == ()
    c2 = Criterion(
        name="severity", question="how bad?",
        possible_values=("low", "medium", "high"),
    )
    assert c2.possible_values == ("low", "medium", "high")


def test_workflow_step_minimum_fields() -> None:
    step = WorkflowStepDefinition(id=1, name="Triage")
    assert step.id == 1
    assert step.name == "Triage"
    assert step.instructions == ""
    assert step.gate is None
    assert step.evaluates == ()
    assert step.routes == ()
    assert step.effective_todo_name() == "Triage"


def test_effective_todo_name_falls_back_to_name() -> None:
    step = WorkflowStepDefinition(id=1, name="Triage", todo_name="quick_triage")
    assert step.effective_todo_name() == "quick_triage"


def test_route_carries_destination() -> None:
    r = Route(criteria_name="severity", value="high", goto_step=5)
    assert r.goto_step == 5


def test_tool_use_with_optional_note() -> None:
    u = ToolUse(tool_name="goal-manager", note="read the goal first")
    assert u.note == "read the goal first"
    u2 = ToolUse(tool_name="goal-manager")
    assert u2.note is None


def test_workflow_step_full_shape() -> None:
    step = WorkflowStepDefinition(
        id=2,
        name="Decide",
        instructions="Pick a route based on severity.",
        todo_name="decision",
        todo_description="Choose the right path.",
        gate=Gate(checks=(GateCheck(variable="triaged", value="true"),)),
        evaluates=(
            Criterion(
                name="severity", question="how bad?",
                possible_values=("low", "high"),
            ),
        ),
        tool_uses=(ToolUse(tool_name="rule-checker"),),
        subagents=("workflows/escalator",),
        marks_done=("decision",),
        routes=(
            Route(criteria_name="severity", value="high", goto_step=99),
        ),
    )
    assert step.gate is not None
    assert step.evaluates[0].name == "severity"
    assert step.subagents == ("workflows/escalator",)
    assert step.marks_done == ("decision",)
