"""compose_body composition rules: workflow + system_prompt + preamble/postamble."""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt import (
    WorkflowPromptBuilder,
    compose_body,
)
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    ModelParameters,
)
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition


def _agent(
    *, system_prompt: str = "", preamble: str = "", postamble: str = "",
    usage_long: str = "fallback usage doc",
    workflow: list[WorkflowStepDefinition] | None = None,
) -> AgentVariant:
    return AgentVariant(
        postfix="", agent_mode="primary",
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="a", name="a", description=None),
            usage_explanation_long=usage_long,
            usage_explanation_short="s",
            system_prompt=system_prompt,
            preamble=preamble,
            postamble=postamble,
            workflow=workflow or [],
            todo_mode="none",  # keep the workflow output minimal for the tests
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )


def test_no_workflow_no_system_prompt_falls_back_to_usage_long() -> None:
    out = compose_body(_agent(usage_long="hello world"))
    assert out == "hello world"


def test_no_workflow_with_system_prompt_uses_it_as_body() -> None:
    out = compose_body(
        _agent(system_prompt="You are a helpful assistant.", usage_long="ignored")
    )
    assert out == "You are a helpful assistant."


def test_workflow_only_renders_workflow_text() -> None:
    out = compose_body(
        _agent(workflow=[WorkflowStepDefinition(id=1, name="Step")])
    )
    assert "## MANDATORY WORKFLOW" in out
    assert "STEP 1: Step" in out


def test_workflow_with_system_prompt_prepends_system_prompt() -> None:
    out = compose_body(
        _agent(
            system_prompt="System framing here.",
            workflow=[WorkflowStepDefinition(id=1, name="Step")],
        )
    )
    assert out.startswith("System framing here.\n\n")
    assert "## MANDATORY WORKFLOW" in out


def test_preamble_appears_between_system_prompt_and_workflow_header() -> None:
    out = compose_body(
        _agent(
            system_prompt="SYS",
            preamble="# Orchestration Overview",
            workflow=[WorkflowStepDefinition(id=1, name="Step")],
        )
    )
    sys_pos = out.index("SYS")
    pre_pos = out.index("# Orchestration Overview")
    wf_pos = out.index("## MANDATORY WORKFLOW")
    assert sys_pos < pre_pos < wf_pos


def test_postamble_appears_after_final_checklist() -> None:
    out = compose_body(
        _agent(
            postamble="Wrap-up notes here.",
            workflow=[WorkflowStepDefinition(id=1, name="Step")],
        )
    )
    cl_pos = out.index("FINAL CHECKLIST")
    post_pos = out.index("Wrap-up notes here.")
    assert cl_pos < post_pos


def test_preamble_postamble_ignored_when_no_workflow() -> None:
    out = compose_body(
        _agent(
            system_prompt="just-the-system-prompt",
            preamble="ignored-pre", postamble="ignored-post",
        )
    )
    assert out == "just-the-system-prompt"


def test_builder_with_empty_workflow_returns_empty_string() -> None:
    assert WorkflowPromptBuilder().render(_agent()) == ""
