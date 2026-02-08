"""Tests for the compiler module."""

import pytest

from open_agent_compiler._types import (
    ActionDefinition,
    AgentDefinition,
    AgentPermissions,
    SkillDefinition,
    ToolDefinition,
    ToolPermissions,
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


class TestCompiler:
    def test_opencode_output_structure(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent, target="opencode")
        assert result["backend"] == "opencode"
        assert result["agent"]["name"] == "test-agent"
        assert result["model"]["id"] == "claude-sonnet-4-5-20250929"
        assert result["skills"] == []

    def test_tool_is_permission_dict(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        tool = result["tool"]
        assert isinstance(tool, dict)
        assert "bash" in tool
        bash = tool["bash"]
        assert bash["*"] == "deny"
        assert bash["uv run scripts/read_file.py *"] == "allow"

    def test_auto_permissions_include_bool_fields(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        tool = result["tool"]
        assert tool["read"] is False
        assert tool["write"] is False
        assert tool["edit"] is False
        assert tool["task"] is False
        assert tool["todoread"] is False
        assert tool["todowrite"] is False

    def test_scripts_list(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        assert "scripts" in result
        assert "read_file.py" in result["scripts"]

    def test_default_target_is_opencode(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        assert result["backend"] == "opencode"

    def test_unknown_target_raises(self, sample_agent: AgentDefinition):
        with pytest.raises(ValueError, match="Unknown target"):
            compile_agent(sample_agent, target="unknown")

    def test_skills_with_tool_docs(self, sample_agent: AgentDefinition):
        tool = _make_tool("grep", script="grep.py")
        skill = SkillDefinition(
            name="security-review",
            description="Review for security issues",
            instructions="Check OWASP top 10.",
            tools=(tool,),
        )
        agent_with_skills = AgentDefinition(
            name=sample_agent.name,
            description=sample_agent.description,
            config=sample_agent.config,
            tools=sample_agent.tools,
            skills=(skill,),
            skill_instructions=(("security-review", "Use for security audits"),),
            system_prompt=sample_agent.system_prompt,
        )
        result = compile_agent(agent_with_skills)
        assert len(result["skills"]) == 1
        s = result["skills"][0]
        assert s["name"] == "security-review"
        assert s["tools"] == ["grep"]
        assert "## Available Tools" in s["instructions"]
        assert "### grep" in s["instructions"]
        assert "uv run scripts/grep.py" in s["instructions"]

    def test_no_duplicate_bash_permissions(self):
        """Shared tools produce one permission entry."""
        tool = _make_tool("shared")
        skill = SkillDefinition(
            name="my-skill",
            description="A skill",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            tools=(tool,),
            skills=(skill,),
            skill_instructions=(("my-skill", "Use it"),),
        )
        result = compile_agent(agent)
        bash = result["tool"]["bash"]
        allow_keys = [k for k, v in bash.items() if v == "allow"]
        assert len(allow_keys) == 1

    def test_auto_skill_permissions(self):
        """Auto-generated permissions include skill allow/deny."""
        tool = _make_tool("x")
        skill = SkillDefinition(
            name="data-query",
            description="Query data",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("data-query", "Use for data"),),
        )
        result = compile_agent(agent)
        assert "skill" in result["tool"]
        assert result["tool"]["skill"]["data-query"] == "allow"
        assert result["tool"]["skill"]["*"] == "deny"

    def test_explicit_tool_permissions(self):
        """Explicit ToolPermissions override auto-generation."""
        perms = ToolPermissions(
            bash=(("uv run scripts/custom.py *", "allow"), ("*", "deny")),
            read=True,
            write=True,
            edit=False,
            task=False,
            skill=(("my-skill", "allow"), ("*", "deny")),
            mcp=(("zai-mcp-*", False),),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            tool_permissions=perms,
        )
        result = compile_agent(agent)
        tool = result["tool"]
        assert tool["bash"]["uv run scripts/custom.py *"] == "allow"
        assert tool["read"] is True
        assert tool["write"] is True
        assert tool["skill"]["my-skill"] == "allow"
        assert tool["zai-mcp-*"] is False

    def test_agent_permissions(self):
        """AgentPermissions compile into permission: section."""
        perms = AgentPermissions(
            doom_loop="allow",
            task=((".opencode/agents/*.md", "allow"),),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            permissions=perms,
        )
        result = compile_agent(agent)
        assert "permission" in result
        assert result["permission"]["doom_loop"] == "allow"
        assert result["permission"]["task"][".opencode/agents/*.md"] == "allow"

    def test_no_permission_key_when_none(self, sample_agent: AgentDefinition):
        """No permission: key when AgentPermissions is None."""
        result = compile_agent(sample_agent)
        assert "permission" not in result

    def test_mode_in_agent_section(self):
        agent = AgentDefinition(
            name="test",
            description="test",
            mode="primary",
        )
        result = compile_agent(agent)
        assert result["agent"]["mode"] == "primary"

    def test_no_mode_when_empty(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        assert "mode" not in result["agent"]

    def test_deny_first_in_bash(self, sample_agent: AgentDefinition):
        """'*': 'deny' must be first key in auto-generated bash perms."""
        result = compile_agent(sample_agent)
        bash_keys = list(result["tool"]["bash"].keys())
        assert bash_keys[0] == "*"

    def test_deny_first_in_skill(self):
        """'*': 'deny' must be first key in auto-generated skill perms."""
        tool = _make_tool("x")
        skill = SkillDefinition(
            name="data-query",
            description="Query data",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("data-query", "Use for data"),),
        )
        result = compile_agent(agent)
        skill_keys = list(result["tool"]["skill"].keys())
        assert skill_keys[0] == "*"

    def test_skill_instructions_in_output(self):
        """skill_instructions compile into the output."""
        skill = SkillDefinition(
            name="review",
            description="Review code",
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("review", "Use when reviewing PRs"),),
        )
        result = compile_agent(agent)
        assert "skill_instructions" in result
        assert result["skill_instructions"] == [
            ("review", "Use when reviewing PRs"),
        ]
