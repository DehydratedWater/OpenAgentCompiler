"""Tests for the compiler module."""

import pytest

from open_agent_compiler._types import AgentDefinition
from open_agent_compiler.compiler import compile_agent


class TestCompiler:
    def test_claude_code_output(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent, target="claude_code")
        assert result["backend"] == "claude_code"
        assert result["name"] == "test-agent"
        assert result["model"] == "claude-sonnet-4-5-20250929"
        assert result["system_prompt"] == "You are a test agent."
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "read_file"

    def test_opencode_output(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent, target="opencode")
        assert result["backend"] == "opencode"
        assert result["agent"]["name"] == "test-agent"
        assert result["model"]["id"] == "claude-sonnet-4-5-20250929"
        assert len(result["tools"]) == 1

    def test_default_target_is_claude_code(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        assert result["backend"] == "claude_code"

    def test_unknown_target_raises(self, sample_agent: AgentDefinition):
        with pytest.raises(ValueError, match="Unknown target"):
            compile_agent(sample_agent, target="unknown")  # type: ignore[arg-type]
