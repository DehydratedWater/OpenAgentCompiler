"""SECURITY POLICY + Available Subagents rendering."""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.security_policy import (
    render_security_policy,
)
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.subagent_section import (
    render_subagent_section,
)
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    ModelParameters,
    ToolPermissions,
)
from open_agent_compiler.model.core.skills_model import SkillDefinition


def _agent(
    *, mode: str = "primary", workspace: str | None = None,
    subagents: list[AgentHeader] | None = None,
    skills: list[SkillDefinition] | None = None,
    perms: ToolPermissions | None = None,
    inline_skills: bool = False,
    postfix: str = "",
) -> AgentVariant:
    return AgentVariant(
        postfix=postfix, agent_mode=mode,
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="x", name="orch", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            subagents=subagents or [],
            skills=skills or [],
            workspace=workspace,
            tool_permissions=perms,
            inline_skills=inline_skills,
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )


# ---- Available Subagents ------------------------------------------------


def test_subagent_section_empty_when_no_subagents() -> None:
    assert render_subagent_section(_agent()) == ""


def test_subagent_section_lists_task_and_bash_groups() -> None:
    subs = [
        AgentHeader(agent_id="t1", name="persona/quick", description="quick ack",
                    mode="subagent"),
        AgentHeader(agent_id="b1", name="workflows/big", description="big job",
                    mode="primary"),
    ]
    out = render_subagent_section(_agent(subagents=subs))
    assert "## Available Subagents" in out
    assert "persona/quick" in out
    assert 'subagent_type: "persona/quick"' in out
    assert "workflows/big" in out
    assert "uv run scripts/opencode_manager.py run --agent workflows/big" in out


def test_subagent_section_defaults_to_task_mode_when_unspecified() -> None:
    subs = [AgentHeader(agent_id="t1", name="persona/quick", description="d")]
    out = render_subagent_section(_agent(subagents=subs))
    assert 'subagent_type: "persona/quick"' in out


# ---- SECURITY POLICY: ALLOWED -------------------------------------------


def test_allowed_section_no_perms_no_workspace_says_no_to_read_write() -> None:
    out = render_security_policy(_agent())
    assert "- Read files: no" in out
    assert "- Write files: no" in out
    assert "- Use skills: none" in out


def test_allowed_section_workspace_routes_writes_via_workspace_io() -> None:
    out = render_security_policy(
        _agent(workspace=".agent_workspace/{name}", postfix="-glm47")
    )
    assert "Write files: only via workspace_io.py to `.agent_workspace/orch-glm47/`" in out


def test_allowed_section_perms_read_yes() -> None:
    out = render_security_policy(_agent(perms=ToolPermissions(read=True)))
    assert "- Read files: yes" in out


def test_allowed_section_perms_write_unrestricted() -> None:
    out = render_security_policy(_agent(perms=ToolPermissions(write=True)))
    assert "- Write files: yes (unrestricted)" in out


def test_allowed_section_lists_skills_by_name() -> None:
    skills = [
        SkillDefinition(
            name="data-query", description="d",
            usage_explanation_long="l", usage_explanation_short="s",
            rules=[], workflow_steps=[],
            positive_examples=[], negative_examples=[],
        ),
    ]
    out = render_security_policy(_agent(skills=skills))
    assert "- Use skills: `data-query`" in out


def test_allowed_section_says_inline_skills_means_no_skills_callable() -> None:
    skills = [
        SkillDefinition(
            name="data-query", description="d",
            usage_explanation_long="l", usage_explanation_short="s",
            rules=[], workflow_steps=[],
            positive_examples=[], negative_examples=[],
        ),
    ]
    out = render_security_policy(_agent(skills=skills, inline_skills=True))
    assert "Use skills: none (bash scripts are documented in prompt)" in out


# ---- SECURITY POLICY: FORBIDDEN -----------------------------------------


def test_forbidden_no_writes_forbids_file_creation_bash() -> None:
    out = render_security_policy(_agent())
    assert "Write, create, or modify any files" in out
    assert "cat >" in out


def test_forbidden_with_workspace_forbids_outside_writes() -> None:
    out = render_security_policy(_agent(workspace=".agent_workspace/{name}"))
    assert "Write or create files using the write/edit tools" in out
    assert "Store thoughts, notes, analyses" in out


def test_forbidden_subagent_mode_no_children_blocks_task_tool() -> None:
    out = render_security_policy(_agent(mode="subagent"))
    assert "Invoke other agents via Task tool" in out
    assert "subagents cannot delegate to other subagents" in out


def test_forbidden_lists_specific_skills_when_present() -> None:
    skills = [
        SkillDefinition(
            name="data-query", description="d",
            usage_explanation_long="l", usage_explanation_short="s",
            rules=[], workflow_steps=[],
            positive_examples=[], negative_examples=[],
        ),
    ]
    out = render_security_policy(_agent(skills=skills))
    assert "Use skills other than the ones listed above" in out


def test_forbidden_mcp_disabled_by_default() -> None:
    out = render_security_policy(_agent())
    assert "Use MCP tools (they are disabled)" in out


def test_forbidden_mcp_skipped_when_perms_allow_mcp() -> None:
    out = render_security_policy(_agent(perms=ToolPermissions(mcp=True)))
    assert "Use MCP tools" not in out


# ---- compose_body integration -------------------------------------------


def test_compose_body_appends_security_policy_for_workflow_agent() -> None:
    from open_agent_compiler.compiler.dialects.opencode.workflow_prompt import compose_body
    from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition

    agent = AgentVariant(
        postfix="", agent_mode="primary",
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="x", name="orch", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            workflow=[WorkflowStepDefinition(id=1, name="Step")],
            todo_mode="none",
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )
    out = compose_body(agent)
    assert "## SECURITY POLICY" in out
    assert out.index("FINAL CHECKLIST") < out.index("## SECURITY POLICY")


def test_compose_body_appends_security_policy_when_perms_explicit_no_workflow() -> None:
    from open_agent_compiler.compiler.dialects.opencode.workflow_prompt import compose_body

    agent = _agent(perms=ToolPermissions(read=True))
    out = compose_body(agent)
    assert "## SECURITY POLICY" in out


def test_compose_body_skips_security_for_plain_non_workflow_agent() -> None:
    from open_agent_compiler.compiler.dialects.opencode.workflow_prompt import compose_body

    out = compose_body(_agent())
    assert "## SECURITY POLICY" not in out
