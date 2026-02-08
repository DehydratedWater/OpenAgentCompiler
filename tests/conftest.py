"""Shared test fixtures."""

from typing import Any

import pytest

from open_agent_compiler._types import (
    AgentConfig,
    AgentDefinition,
    ModelProvider,
    ParameterDefinition,
    SkillDefinition,
    StreamFormat,
    ToolDefinition,
)
from open_agent_compiler.builders import (
    AgentBuilder,
    ConfigBuilder,
    SkillBuilder,
    ToolBuilder,
)
from open_agent_compiler.compiler import compile_agent


@pytest.fixture
def sample_tool() -> ToolDefinition:
    return ToolDefinition(
        name="read_file",
        description="Read a file from disk",
        file_path="read_file.py",
        parameters=(
            ParameterDefinition(
                name="path",
                description="Path to file",
                param_type="str",
                required=True,
            ),
        ),
    )


@pytest.fixture
def sample_tool_with_stream() -> ToolDefinition:
    return ToolDefinition(
        name="db_query",
        description="Execute SQL queries",
        file_path="db_query.py",
        parameters=(
            ParameterDefinition(
                name="sql",
                description="SQL query to execute",
                param_type="str",
                required=True,
            ),
            ParameterDefinition(
                name="timeout",
                description="Timeout in seconds",
                param_type="int",
                required=False,
                default="60",
            ),
        ),
        stream_format=StreamFormat.TEXT,
        stream_field="sql",
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


@pytest.fixture
def sample_compiled(
    sample_agent: AgentDefinition,
    sample_skill: SkillDefinition,
) -> dict[str, Any]:
    """Compile a full agent (with skills) for writer tests."""
    agent_with_skill = AgentDefinition(
        name=sample_agent.name,
        description=sample_agent.description,
        config=sample_agent.config,
        tools=sample_agent.tools,
        skills=(sample_skill,),
        system_prompt=sample_agent.system_prompt,
    )
    return compile_agent(agent_with_skill, target="opencode")
