"""todo_block: STEP 0, workspace init, mark-done, strict verification."""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt import WorkflowPromptBuilder
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.todo_block import (
    render_mark_done,
    render_strict_verification,
    render_todo_step_0,
    render_workspace_init,
)
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    ModelParameters,
)
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition


def _agent(
    *, mode: str = "primary", todo_mode: str = "strict",
    workspace: str | None = None, postfix: str = "",
    workflow: list[WorkflowStepDefinition] | None = None,
) -> AgentVariant:
    return AgentVariant(
        postfix=postfix, agent_mode=mode,
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="x", name="orch", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            workflow=workflow or [],
            todo_mode=todo_mode,
            workspace=workspace,
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )


# ---- workspace init ------------------------------------------------------


def test_workspace_init_omitted_when_workspace_unset() -> None:
    assert render_workspace_init(_agent()) == ""


def test_workspace_init_substitutes_agent_name_with_postfix() -> None:
    a = _agent(workspace=".agent_workspace/{name}", postfix="-glm47")
    out = render_workspace_init(a)
    assert "uv run scripts/workspace_io.py --command init --workspace .agent_workspace/orch-glm47" in out
    assert "STEP 0a" in out


# ---- STEP 0 task list ----------------------------------------------------


def _two_step_workflow() -> list[WorkflowStepDefinition]:
    return [
        WorkflowStepDefinition(id=1, name="Triage", todo_description="read msg"),
        WorkflowStepDefinition(id=2, name="Respond"),
    ]


def test_strict_subagent_step_0_emits_init_and_add_per_task() -> None:
    a = _agent(mode="subagent", todo_mode="strict", workflow=_two_step_workflow())
    out = render_todo_step_0(a)
    assert 'uv run scripts/subagent_todo.py init "orch"' in out
    # Two tasks, two add commands
    assert out.count('subagent_todo.py add "orch"') == 2
    assert '--subject "Triage"' in out
    assert '--description "read msg"' in out
    # Task without description omits --description
    assert '--subject "Respond"' in out


def test_strict_primary_step_0_uses_todowrite() -> None:
    a = _agent(mode="primary", todo_mode="strict", workflow=_two_step_workflow())
    out = render_todo_step_0(a)
    assert "Use todowrite to create these tasks:" in out
    assert "subagent_todo.py" not in out
    assert '1. "Triage" - read msg' in out
    assert '2. "Respond"' in out


def test_lazy_mode_does_not_include_per_step_marks() -> None:
    a = _agent(mode="primary", todo_mode="lazy", workflow=_two_step_workflow())
    out = render_todo_step_0(a)
    assert "STEP 0" in out
    assert "You do NOT need to update task status" in out


def test_none_mode_emits_no_step_0() -> None:
    a = _agent(mode="primary", todo_mode="none", workflow=_two_step_workflow())
    assert render_todo_step_0(a) == ""


# ---- mark-done -----------------------------------------------------------


def test_mark_done_strict_subagent_uses_subagent_todo_bash() -> None:
    a = _agent(mode="subagent", todo_mode="strict")
    out = render_mark_done(a, ("Triage",))
    assert "**Mark task as completed:**" in out
    assert 'subagent_todo.py update "orch"' in out


def test_mark_done_strict_primary_uses_todowrite() -> None:
    a = _agent(mode="primary", todo_mode="strict")
    out = render_mark_done(a, ("Triage",))
    assert '**todowrite: Mark "Triage" as done**' in out


def test_mark_done_lazy_emits_nothing() -> None:
    a = _agent(todo_mode="lazy")
    assert render_mark_done(a, ("Triage",)) == ""


def test_mark_done_none_emits_nothing() -> None:
    a = _agent(todo_mode="none")
    assert render_mark_done(a, ("Triage",)) == ""


def test_mark_done_empty_names_emits_nothing() -> None:
    a = _agent(todo_mode="strict")
    assert render_mark_done(a, ()) == ""


# ---- final-checklist verification ----------------------------------------


def test_strict_subagent_verification_uses_subagent_todo_list() -> None:
    a = _agent(mode="subagent", todo_mode="strict")
    out = render_strict_verification(a)
    assert 'subagent_todo.py list "orch"' in out
    assert "completed" in out


def test_strict_primary_verification_says_use_todoread() -> None:
    a = _agent(mode="primary", todo_mode="strict")
    out = render_strict_verification(a)
    assert "todoread" in out


def test_lazy_verification_emits_nothing() -> None:
    assert render_strict_verification(_agent(todo_mode="lazy")) == ""


def test_none_verification_emits_nothing() -> None:
    assert render_strict_verification(_agent(todo_mode="none")) == ""


# ---- end-to-end through the builder --------------------------------------


def test_full_builder_includes_workspace_then_step_0_then_steps() -> None:
    a = _agent(
        mode="subagent", todo_mode="strict",
        workspace=".agent_workspace/{name}",
        workflow=[
            WorkflowStepDefinition(id=1, name="Triage", marks_done=("Triage",)),
        ],
    )
    out = WorkflowPromptBuilder().render(a)
    assert out.index("STEP 0a") < out.index("STEP 0:") < out.index("STEP 1:")
    assert "`subagent_todo.py` to track your progress" in out


def test_full_builder_under_none_mode_omits_all_todo_references() -> None:
    a = _agent(
        mode="primary", todo_mode="none",
        workflow=[WorkflowStepDefinition(id=1, name="Just do it")],
    )
    out = WorkflowPromptBuilder().render(a)
    assert "STEP 0" not in out
    assert "subagent_todo" not in out
    assert "todowrite" not in out
    assert "FROM YOUR TODO LIST" not in out
