"""skills_section: inline_skills True/False rendering."""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt import WorkflowPromptBuilder
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.skills_section import (
    render_skills_section,
)
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    ModelParameters,
)
from open_agent_compiler.model.core.permissions_model import BashToolPermission
from open_agent_compiler.model.core.skills_model import SkillDefinition, WorkflowStep
from open_agent_compiler.model.core.tools_model import (
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
)
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name=name, description=f"{name} does things",
            usage_explanation_long=f"Use {name} to do things.",
            usage_explanation_short="short", rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(tool_name="bash", value="allow"),
            positive_examples=[f"uv run scripts/{name}.py --x 1"],
            negative_examples=[],
            mode_specific_rules=[],
        ),
    )


def _skill(name: str, tools: list[ToolDefinition]) -> SkillDefinition:
    return SkillDefinition(
        name=name, description=f"{name} skill",
        usage_explanation_long=f"Use {name} when needed.",
        usage_explanation_short="short", rules=[],
        workflow_steps=[
            WorkflowStep(
                header="step", condition=None, result=None, rule="r",
                tools_used=tools,
            )
        ],
        positive_examples=[], negative_examples=[],
    )


def _agent(*, inline: bool, skills: list[SkillDefinition]) -> AgentVariant:
    return AgentVariant(
        postfix="", agent_mode="primary",
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="a", name="a", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            skills=skills,
            inline_skills=inline,
            todo_mode="none",
            workflow=[WorkflowStepDefinition(id=1, name="Step")],
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )


def test_no_skills_emits_empty_string() -> None:
    a = AgentVariant(
        postfix="", agent_mode="primary",
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="a", name="a", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            inline_skills=False,
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )
    assert render_skills_section(a) == ""


def test_reference_mode_lists_tool_names_per_skill() -> None:
    skill = _skill("data-query", [_tool("db-query"), _tool("file-search")])
    out = render_skills_section(_agent(inline=False, skills=[skill]))
    assert "## Your Skills (use via bash)" in out
    assert "### data-query skill" in out
    assert "Tools: `db-query`, `file-search`" in out
    # No inline bash examples
    assert "uv run scripts/db-query.py" not in out


def test_inline_mode_emits_action_docs_per_tool() -> None:
    skill = _skill("data-query", [_tool("db-query")])
    out = render_skills_section(_agent(inline=True, skills=[skill]))
    assert "## Available Bash Scripts" in out
    assert "These are NOT callable tools" in out
    assert "#### `db-query` — db-query does things" in out
    assert "uv run scripts/db-query.py --x 1" in out


def test_inline_mode_dedupes_tools_across_workflow_steps() -> None:
    shared = _tool("shared-tool")
    skill = SkillDefinition(
        name="multi-step", description="multi",
        usage_explanation_long="l", usage_explanation_short="s", rules=[],
        workflow_steps=[
            WorkflowStep(
                header="a", condition=None, result=None, rule="r",
                tools_used=[shared],
            ),
            WorkflowStep(
                header="b", condition=None, result=None, rule="r",
                tools_used=[shared],
            ),
        ],
        positive_examples=[], negative_examples=[],
    )
    out = render_skills_section(_agent(inline=True, skills=[skill]))
    assert out.count("#### `shared-tool`") == 1


def test_builder_includes_skills_between_preamble_and_workflow_header() -> None:
    skill = _skill("data-query", [_tool("db-query")])
    a = _agent(inline=False, skills=[skill])
    # Add a preamble to the agent
    a = a.model_copy(
        update={
            "agent_definition": a.agent_definition.model_copy(
                update={"preamble": "PREAMBLE"}
            )
        }
    )
    out = WorkflowPromptBuilder().render(a)
    assert out.index("PREAMBLE") < out.index("## Your Skills") < out.index("## MANDATORY WORKFLOW")
