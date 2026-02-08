"""Tests for the compiler module."""

import pytest

from open_agent_compiler._types import (
    AgentDefinition,
    ParameterDefinition,
    SkillDefinition,
    StreamFormat,
    ToolDefinition,
)
from open_agent_compiler.compiler import compile_agent


class TestCompiler:
    def test_opencode_output_structure(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent, target="opencode")
        assert result["backend"] == "opencode"
        assert result["agent"]["name"] == "test-agent"
        assert result["model"]["id"] == "claude-sonnet-4-5-20250929"
        assert result["skills"] == []

    def test_tools_is_bash_permission_dict(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        tools = result["tools"]
        assert isinstance(tools, dict)
        assert "bash" in tools
        bash = tools["bash"]
        assert bash["*"] == "deny"
        assert bash["uv run scripts/read_file.py *"] == "allow"

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
        tool = ToolDefinition(
            name="grep",
            description="Search files",
            file_path="grep.py",
            parameters=(
                ParameterDefinition(
                    name="pattern",
                    description="Regex pattern",
                    param_type="str",
                ),
            ),
        )
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
            system_prompt=sample_agent.system_prompt,
        )
        result = compile_agent(agent_with_skills)
        assert len(result["skills"]) == 1
        s = result["skills"][0]
        assert s["name"] == "security-review"
        assert s["tools"] == ["grep"]
        # Instructions should contain auto-appended tool docs
        assert "## Available Tools" in s["instructions"]
        assert "### grep" in s["instructions"]
        assert "uv run scripts/grep.py" in s["instructions"]

    def test_no_duplicate_bash_permissions(self):
        """Shared tools produce one permission entry."""
        tool = ToolDefinition(
            name="shared",
            description="Shared tool",
            file_path="shared.py",
        )
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
        )
        result = compile_agent(agent)
        bash = result["tools"]["bash"]
        # Count how many times the permission appears (should be once via dict)
        allow_keys = [k for k, v in bash.items() if v == "allow"]
        assert len(allow_keys) == 1

    def test_stream_tool_docs_in_skill(self):
        tool = ToolDefinition(
            name="db_query",
            description="Execute SQL",
            file_path="db_query.py",
            parameters=(
                ParameterDefinition(
                    name="sql", description="SQL query", param_type="str"
                ),
                ParameterDefinition(
                    name="timeout",
                    description="Timeout",
                    param_type="int",
                    required=False,
                    default="60",
                ),
            ),
            stream_format=StreamFormat.TEXT,
            stream_field="sql",
        )
        skill = SkillDefinition(
            name="data",
            description="Data skill",
            instructions="Query data.",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
        )
        result = compile_agent(agent)
        instructions = result["skills"][0]["instructions"]
        assert "Stdin streaming" in instructions
        assert "stdin as text" in instructions
