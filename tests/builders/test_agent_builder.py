"""Tests for AgentBuilder."""

import pytest

from open_agent_compiler._types import AgentConfig, SkillDefinition, ToolDefinition
from open_agent_compiler.builders import AgentBuilder


class TestAgentBuilder:
    def test_build_minimal(self, agent_builder: AgentBuilder):
        agent = agent_builder.name("bot").description("A bot").build()
        assert agent.name == "bot"
        assert agent.description == "A bot"
        assert agent.tools == ()
        assert agent.system_prompt == ""

    def test_build_full(
        self,
        agent_builder: AgentBuilder,
        sample_tool: ToolDefinition,
        sample_config: AgentConfig,
    ):
        agent = (
            agent_builder.name("bot")
            .description("A bot")
            .config(sample_config)
            .tool(sample_tool)
            .system_prompt("Be helpful.")
            .build()
        )
        assert agent.config == sample_config
        assert agent.tools == (sample_tool,)
        assert agent.system_prompt == "Be helpful."

    def test_fluent_returns_self(self, agent_builder: AgentBuilder):
        ret = agent_builder.name("x")
        assert ret is agent_builder

    def test_missing_name_raises(self, agent_builder: AgentBuilder):
        with pytest.raises(ValueError, match="name"):
            agent_builder.description("d").build()

    def test_missing_description_raises(self, agent_builder: AgentBuilder):
        with pytest.raises(ValueError, match="description"):
            agent_builder.name("n").build()

    def test_reset_clears_state(self, agent_builder: AgentBuilder):
        agent_builder.name("bot").description("A bot").system_prompt("Hi")
        agent_builder.reset()
        with pytest.raises(ValueError, match="name"):
            agent_builder.build()

    def test_multiple_tools(self, agent_builder: AgentBuilder):
        t1 = ToolDefinition(name="a", description="A")
        t2 = ToolDefinition(name="b", description="B")
        agent = agent_builder.name("bot").description("d").tool(t1).tool(t2).build()
        assert len(agent.tools) == 2
        assert agent.tools[0].name == "a"
        assert agent.tools[1].name == "b"

    def test_agent_with_skills(self, agent_builder: AgentBuilder):
        skill = SkillDefinition(name="review", description="Review code")
        agent = agent_builder.name("bot").description("A bot").skill(skill).build()
        assert len(agent.skills) == 1
        assert agent.skills[0].name == "review"

    def test_built_agent_is_frozen(self, agent_builder: AgentBuilder):
        agent = agent_builder.name("x").description("d").build()
        with pytest.raises(AttributeError):
            agent.name = "y"  # type: ignore[misc]
