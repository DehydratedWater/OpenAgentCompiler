"""WorkflowPromptBuilder skeleton: header, steps, final checklist."""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt import WorkflowPromptBuilder
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    ModelParameters,
)
from open_agent_compiler.model.core.workflow_model import (
    Criterion,
    Gate,
    GateCheck,
    Route,
    ToolUse,
    WorkflowStepDefinition,
)


def _variant(workflow: list[WorkflowStepDefinition]) -> AgentVariant:
    return AgentVariant(
        postfix="", agent_mode="primary",
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="x", name="orch", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            workflow=workflow,
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )


def test_empty_workflow_returns_empty_string() -> None:
    builder = WorkflowPromptBuilder()
    assert builder.render(_variant([])) == ""


def test_single_step_workflow_renders_header_step_and_checklist() -> None:
    step = WorkflowStepDefinition(
        id=1, name="Triage", instructions="Read the message.",
    )
    out = WorkflowPromptBuilder().render(_variant([step]))
    assert "## MANDATORY WORKFLOW" in out
    assert "### STEP 1: Triage" in out
    assert "Read the message." in out
    assert "## FINAL CHECKLIST" in out
    assert '- ✅ Did I complete "Triage"?' in out


def test_gate_single_check_rendered_inline() -> None:
    step = WorkflowStepDefinition(
        id=1, name="Decide",
        gate=Gate(checks=(GateCheck(variable="kind", value="urgent"),)),
    )
    out = WorkflowPromptBuilder().render(_variant([step]))
    assert "**Condition:** Only execute if `kind` = `urgent`" in out


def test_gate_multiple_checks_listed_with_logic() -> None:
    step = WorkflowStepDefinition(
        id=1, name="Decide",
        gate=Gate(
            logic="any",
            checks=(
                GateCheck(variable="kind", value="urgent"),
                GateCheck(variable="vip", value="true"),
            ),
        ),
    )
    out = WorkflowPromptBuilder().render(_variant([step]))
    assert "(ANY must be true)" in out
    assert "- `kind` = `urgent`" in out
    assert "- `vip` = `true`" in out


def test_criteria_block_lists_questions_and_values() -> None:
    step = WorkflowStepDefinition(
        id=1, name="Score",
        evaluates=(
            Criterion(
                name="severity", question="how bad?",
                possible_values=("low", "high"),
            ),
        ),
    )
    out = WorkflowPromptBuilder().render(_variant([step]))
    assert "**Evaluate the following criteria:**" in out
    assert "- **severity**: how bad?" in out
    assert "Possible values: `low` | `high`" in out


def test_tool_uses_block_lists_with_notes() -> None:
    step = WorkflowStepDefinition(
        id=1, name="Use",
        tool_uses=(
            ToolUse(tool_name="goal-manager", note="read the goal"),
            ToolUse(tool_name="logger"),
        ),
    )
    out = WorkflowPromptBuilder().render(_variant([step]))
    assert "**Use these tools:**" in out
    assert "- `goal-manager` — read the goal" in out
    assert "- `logger`" in out


def test_subagent_invocation_emitted_per_subagent() -> None:
    step = WorkflowStepDefinition(
        id=1, name="Delegate", subagents=("persona/quick-ack", "workflows/escalate"),
    )
    out = WorkflowPromptBuilder().render(_variant([step]))
    assert "**Invoke `persona/quick-ack` via Task tool:**" in out
    assert "**Invoke `workflows/escalate` via Task tool:**" in out


def test_routes_block_lists_destinations() -> None:
    step = WorkflowStepDefinition(
        id=1, name="Route",
        evaluates=(Criterion(name="severity", question="how bad?"),),
        routes=(
            Route(criteria_name="severity", value="high", goto_step=99),
            Route(criteria_name="severity", value="low", goto_step=42),
        ),
    )
    out = WorkflowPromptBuilder().render(_variant([step]))
    assert "**Based on evaluation, route to:**" in out
    assert "- If `severity` = `high` → Go to **STEP 99**" in out
    assert "- If `severity` = `low` → Go to **STEP 42**" in out


def test_final_checklist_dedupes_by_effective_todo_name() -> None:
    s1 = WorkflowStepDefinition(id=1, name="One", todo_name="shared")
    s2 = WorkflowStepDefinition(id=2, name="Two", todo_name="shared")
    # Use todo_mode="none" so the STEP 0 task list doesn't also list "shared".
    variant = _variant([s1, s2])
    variant_no_todo = variant.model_copy(
        update={
            "agent_definition": variant.agent_definition.model_copy(
                update={"todo_mode": "none"}
            )
        }
    )
    out = WorkflowPromptBuilder().render(variant_no_todo)
    # Only one checklist entry for "shared"
    assert out.count('"shared"') == 1


def test_steps_rendered_in_order_with_divider() -> None:
    steps = [
        WorkflowStepDefinition(id=1, name="First"),
        WorkflowStepDefinition(id=2, name="Second"),
        WorkflowStepDefinition(id=3, name="Third"),
    ]
    out = WorkflowPromptBuilder().render(_variant(steps))
    assert out.index("First") < out.index("Second") < out.index("Third")
    # Each step block ends with a --- divider
    assert out.count("\n---\n") >= 3
