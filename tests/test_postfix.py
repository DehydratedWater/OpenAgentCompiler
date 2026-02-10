"""Tests for postfix compilation support."""

from open_agent_compiler._types import (
    ActionDefinition,
    AgentDefinition,
    SkillDefinition,
    SubagentDefinition,
    ToolDefinition,
    WorkflowStepDefinition,
)
from open_agent_compiler.compiler import compile_agent


def _make_tool(name: str, *, script: str | None = None) -> ToolDefinition:
    script = script or f"{name}.py"
    return ToolDefinition(
        name=name,
        description=f"Tool {name}",
        actions=(
            ActionDefinition(
                command_pattern=f"uv run scripts/{script} *",
                description=f"Run {name}",
                usage_example=f"uv run scripts/{script} --arg val",
            ),
        ),
        script_files=(script,),
    )


POSTFIX = "-test-abc"


class TestPostfixCompilation:
    def test_agent_name_has_postfix(self):
        agent = AgentDefinition(name="my-agent", description="test")
        result = compile_agent(agent, postfix=POSTFIX)
        assert result["agent"]["name"] == "my-agent-test-abc"

    def test_no_postfix_unchanged(self):
        agent = AgentDefinition(name="my-agent", description="test")
        result = compile_agent(agent, postfix="")
        assert result["agent"]["name"] == "my-agent"

    def test_subagent_refs_in_permissions(self):
        subs = (
            SubagentDefinition(
                name="persona/quick_ack",
                description="Quick acknowledgment",
            ),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            subagents=subs,
        )
        result = compile_agent(agent, postfix=POSTFIX)
        perm = result["permission"]
        assert "task" in perm
        assert f"persona/quick_ack{POSTFIX}" in perm["task"]

    def test_subagent_md_names_have_postfix(self):
        subs = (
            SubagentDefinition(
                name="persona/quick_ack",
                description="Quick acknowledgment",
            ),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            subagents=subs,
        )
        result = compile_agent(agent, postfix=POSTFIX)
        sa_compiled = result["subagents_compiled"]
        assert len(sa_compiled) == 1
        assert sa_compiled[0]["name"] == f"quick_ack{POSTFIX}"
        assert sa_compiled[0]["agent_dir"] == "persona"

    def test_subagent_section_in_prompt(self):
        subs = (
            SubagentDefinition(
                name="persona/quick_ack",
                description="Quick acknowledgment",
            ),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            system_prompt="You are a test agent.",
            subagents=subs,
        )
        result = compile_agent(agent, postfix=POSTFIX)
        prompt = result["agent"]["system_prompt"]
        assert f"persona/quick_ack{POSTFIX}" in prompt

    def test_security_policy_has_postfixed_subagents(self):
        subs = (
            SubagentDefinition(
                name="helper/sub1",
                description="A helper",
            ),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            subagents=subs,
        )
        result = compile_agent(agent, postfix=POSTFIX)
        prompt = result["agent"]["system_prompt"]
        assert f"`helper/sub1{POSTFIX}`" in prompt

    def test_skill_names_not_postfixed(self):
        tool = _make_tool("grep")
        skill = SkillDefinition(
            name="security-review",
            description="Review for security issues",
            instructions="Check OWASP top 10.",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("security-review", "Use for audits"),),
        )
        result = compile_agent(agent, postfix=POSTFIX)
        assert len(result["skills"]) == 1
        assert result["skills"][0]["name"] == "security-review"
        # Skill permission names should not be postfixed
        skill_perms = result["tool"]["skill"]
        assert "security-review" in skill_perms

    def test_workspace_resolves_with_postfixed_name(self):
        agent = AgentDefinition(
            name="my-agent",
            description="test",
            workspace=".agent_workspace/{name}",
        )
        result = compile_agent(agent, postfix=POSTFIX)
        bash = result["tool"]["bash"]
        expected = "uv run scripts/workspace_io.py *"
        assert expected in bash

    def test_workflow_subagent_todo_uses_postfixed_name(self):
        step = WorkflowStepDefinition(
            id=1,
            name="Do stuff",
            instructions="Do the thing",
            marks_done=("Do stuff",),
        )
        agent = AgentDefinition(
            name="my-agent",
            description="test",
            mode="subagent",
            workflow=(step,),
        )
        result = compile_agent(agent, postfix=POSTFIX)
        prompt = result["agent"]["system_prompt"]
        assert f'subagent_todo.py init "my-agent{POSTFIX}"' in prompt

    def test_workflow_step_instructions_postfix_subagent_names(self):
        """Subagent names in workflow step instructions get postfixed."""
        step = WorkflowStepDefinition(
            id=1,
            name="Invoke",
            instructions="Use Task to invoke helper/sub1 for the job.",
            marks_done=("Invoke",),
        )
        subs = (
            SubagentDefinition(
                name="helper/sub1",
                description="A helper",
            ),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            subagents=subs,
            workflow=(step,),
        )
        result = compile_agent(agent, postfix=POSTFIX)
        prompt = result["agent"]["system_prompt"]
        # Step instruction should have the postfixed name
        assert f"helper/sub1{POSTFIX}" in prompt
        # Original un-postfixed name should NOT appear in the prompt
        assert "helper/sub1 " not in prompt.replace(f"helper/sub1{POSTFIX}", "")

    def test_subagent_without_directory(self):
        subs = (
            SubagentDefinition(
                name="simple_sub",
                description="Simple subagent",
            ),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            subagents=subs,
        )
        result = compile_agent(agent, postfix=POSTFIX)
        sa_compiled = result["subagents_compiled"]
        assert sa_compiled[0]["name"] == f"simple_sub{POSTFIX}"
        assert sa_compiled[0]["agent_dir"] == ""
