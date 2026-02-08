"""Tests for the compiler module."""

import pytest

from open_agent_compiler._types import (
    AgentDefinition,
    SkillDefinition,
    ToolDefinition,
)
from open_agent_compiler.compiler import compile_agent


class TestCompiler:
    def test_opencode_output(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent, target="opencode")
        assert result["backend"] == "opencode"
        assert result["agent"]["name"] == "test-agent"
        assert result["model"]["id"] == "claude-sonnet-4-5-20250929"
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "read_file"
        assert result["skills"] == []

    def test_default_target_is_opencode(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        assert result["backend"] == "opencode"

    def test_unknown_target_raises(self, sample_agent: AgentDefinition):
        with pytest.raises(ValueError, match="Unknown target"):
            compile_agent(sample_agent, target="unknown")

    def test_skills_in_output(self, sample_agent: AgentDefinition):
        tool = ToolDefinition(name="grep", description="Search files")
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
        assert s["description"] == "Review for security issues"
        assert s["instructions"] == "Check OWASP top 10."
        assert s["tools"] == ["grep"]
