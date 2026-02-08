"""Tests for AgentBuilder."""

import pytest

from open_agent_compiler._types import (
    ActionDefinition,
    AgentConfig,
    AgentPermissions,
    SkillDefinition,
    ToolDefinition,
    ToolPermissions,
)
from open_agent_compiler.builders import AgentBuilder


def _make_tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Tool {name}",
        actions=(
            ActionDefinition(
                command_pattern=f"uv run scripts/{name}.py *",
                description=f"Run {name}",
                usage_example=f"uv run scripts/{name}.py",
            ),
        ),
        script_files=(f"{name}.py",),
    )


class TestAgentBuilder:
    def test_build_minimal(self, agent_builder: AgentBuilder):
        agent = agent_builder.name("bot").description("A bot").build()
        assert agent.name == "bot"
        assert agent.description == "A bot"
        assert agent.tools == ()
        assert agent.system_prompt == ""
        assert agent.tool_permissions is None
        assert agent.permissions is None
        assert agent.mode == ""

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
        t1 = _make_tool("a")
        t2 = _make_tool("b")
        agent = agent_builder.name("bot").description("d").tool(t1).tool(t2).build()
        assert len(agent.tools) == 2
        assert agent.tools[0].name == "a"
        assert agent.tools[1].name == "b"

    def test_agent_with_skills(self, agent_builder: AgentBuilder):
        skill = SkillDefinition(name="review", description="Review code")
        agent = (
            agent_builder.name("bot")
            .description("A bot")
            .skill(skill, instruction="Use when reviewing code")
            .build()
        )
        assert len(agent.skills) == 1
        assert agent.skills[0].name == "review"
        assert agent.skill_instructions == (("review", "Use when reviewing code"),)

    def test_built_agent_is_frozen(self, agent_builder: AgentBuilder):
        agent = agent_builder.name("x").description("d").build()
        with pytest.raises(AttributeError):
            agent.name = "y"  # type: ignore[misc]

    def test_tool_permissions(self, agent_builder: AgentBuilder):
        perms = ToolPermissions(
            bash=(
                ("uv run scripts/x.py *", "allow"),
                ("*", "deny"),
            ),
            read=True,
            write=False,
            edit=False,
            task=False,
        )
        agent = (
            agent_builder.name("bot").description("d").tool_permissions(perms).build()
        )
        assert agent.tool_permissions is perms
        assert agent.tool_permissions.read is True

    def test_agent_permissions(self, agent_builder: AgentBuilder):
        perms = AgentPermissions(
            doom_loop="allow",
            task=((".opencode/agents/*.md", "allow"),),
        )
        agent = agent_builder.name("bot").description("d").permissions(perms).build()
        assert agent.permissions is perms
        assert agent.permissions.doom_loop == "allow"

    def test_mode(self, agent_builder: AgentBuilder):
        agent = agent_builder.name("bot").description("d").mode("primary").build()
        assert agent.mode == "primary"
