"""Tests for skill inlining compilation support."""

from open_agent_compiler._types import (
    ActionDefinition,
    AgentDefinition,
    SkillDefinition,
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


class TestInlineSkills:
    def test_compiled_skills_empty_when_inlined(self):
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
        result = compile_agent(agent, inline_skills=True)
        assert result["skills"] == []

    def test_skill_permission_disabled_when_inlined(self):
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
        result = compile_agent(agent, inline_skills=True)
        assert result["tool"]["skill"] is False

    def test_system_prompt_has_inlined_section(self):
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
            system_prompt="You are a test agent.",
            skills=(skill,),
            skill_instructions=(("security-review", "Use for audits"),),
        )
        result = compile_agent(agent, inline_skills=True)
        prompt = result["agent"]["system_prompt"]
        assert "## Available Bash Scripts" in prompt
        assert "Check OWASP top 10." in prompt
        # Tool action docs should be inline
        assert "#### Script: grep" in prompt
        assert "uv run scripts/grep.py" in prompt

    def test_workflow_prompt_has_inlined_section(self):
        tool = _make_tool("db_query")
        skill = SkillDefinition(
            name="data-query",
            description="Query data",
            instructions="Use SQL to query.",
            tools=(tool,),
        )
        step = WorkflowStepDefinition(
            id=1,
            name="Query",
            instructions="Run a query",
            marks_done=("Query",),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("data-query", "Use for data"),),
            workflow=(step,),
        )
        result = compile_agent(agent, inline_skills=True)
        prompt = result["agent"]["system_prompt"]
        assert "## Available Bash Scripts" in prompt
        assert "## Your Skills" not in prompt
        assert "Use SQL to query." in prompt
        assert "#### Script: db_query" in prompt

    def test_bash_permissions_still_generated_for_skill_tools(self):
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
        result = compile_agent(agent, inline_skills=True)
        bash = result["tool"]["bash"]
        assert "uv run scripts/grep.py *" in bash
        assert bash["uv run scripts/grep.py *"] == "allow"

    def test_inline_false_unchanged(self):
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
        result = compile_agent(agent, inline_skills=False)
        assert len(result["skills"]) == 1
        assert result["skills"][0]["name"] == "security-review"
        assert result["tool"]["skill"]["security-review"] == "allow"

    def test_security_policy_says_inlined(self):
        tool = _make_tool("grep")
        skill = SkillDefinition(
            name="security-review",
            description="Review for security issues",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("security-review", "Use for audits"),),
        )
        result = compile_agent(agent, inline_skills=True)
        prompt = result["agent"]["system_prompt"]
        assert "none (bash scripts are documented in prompt)" in prompt

    def test_combined_postfix_and_inline(self):
        tool = _make_tool("grep")
        skill = SkillDefinition(
            name="security-review",
            description="Review",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("security-review", "Use it"),),
        )
        result = compile_agent(agent, postfix="-test-x", inline_skills=True)
        assert result["agent"]["name"] == "test-test-x"
        assert result["skills"] == []
        assert result["tool"]["skill"] is False
        prompt = result["agent"]["system_prompt"]
        assert "## Available Bash Scripts" in prompt
