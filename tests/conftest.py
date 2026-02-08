"""Shared test fixtures."""

import pytest

from open_agent_compiler._types import (
    AgentConfig,
    AgentDefinition,
    ModelProvider,
    SkillDefinition,
    ToolDefinition,
)
from open_agent_compiler.builders import (
    AgentBuilder,
    ConfigBuilder,
    SkillBuilder,
    ToolBuilder,
)


@pytest.fixture
def sample_tool() -> ToolDefinition:
    return ToolDefinition(
        name="read_file",
        description="Read a file from disk",
        parameters={"path": {"type": "string"}},
    )


@pytest.fixture
def sample_config() -> AgentConfig:
    return AgentConfig(
        model="claude-sonnet-4-5-20250929",
        provider=ModelProvider.ANTHROPIC,
        temperature=0.0,
        max_tokens=4096,
    )


@pytest.fixture
def sample_agent(
    sample_config: AgentConfig, sample_tool: ToolDefinition
) -> AgentDefinition:
    return AgentDefinition(
        name="test-agent",
        description="A test agent",
        config=sample_config,
        tools=(sample_tool,),
        system_prompt="You are a test agent.",
    )


@pytest.fixture
def agent_builder() -> AgentBuilder:
    return AgentBuilder()


@pytest.fixture
def config_builder() -> ConfigBuilder:
    return ConfigBuilder()


@pytest.fixture
def sample_skill(sample_tool: ToolDefinition) -> SkillDefinition:
    return SkillDefinition(
        name="code-review",
        description="Review code for issues",
        instructions="Carefully review the code for bugs and style issues.",
        tools=(sample_tool,),
    )


@pytest.fixture
def tool_builder() -> ToolBuilder:
    return ToolBuilder()


@pytest.fixture
def skill_builder() -> SkillBuilder:
    return SkillBuilder()
