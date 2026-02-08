"""Tests for SkillBuilder."""

import pytest

from open_agent_compiler._types import ToolDefinition
from open_agent_compiler.builders import SkillBuilder


class TestSkillBuilder:
    def test_build_minimal(self, skill_builder: SkillBuilder):
        skill = skill_builder.name("review").description("Review code").build()
        assert skill.name == "review"
        assert skill.description == "Review code"
        assert skill.instructions == ""
        assert skill.tools == ()

    def test_build_with_tools(self, skill_builder: SkillBuilder):
        t1 = ToolDefinition(
            name="grep", description="Search files", file_path="grep.py"
        )
        t2 = ToolDefinition(
            name="read_file", description="Read a file", file_path="read_file.py"
        )
        skill = (
            skill_builder.name("review")
            .description("Review code")
            .instructions("Check for bugs.")
            .tool(t1)
            .tool(t2)
            .build()
        )
        assert skill.instructions == "Check for bugs."
        assert len(skill.tools) == 2
        assert skill.tools[0].name == "grep"
        assert skill.tools[1].name == "read_file"

    def test_fluent_returns_self(self, skill_builder: SkillBuilder):
        ret = skill_builder.name("x")
        assert ret is skill_builder

    def test_missing_name_raises(self, skill_builder: SkillBuilder):
        with pytest.raises(ValueError, match="name"):
            skill_builder.description("d").build()

    def test_missing_description_raises(self, skill_builder: SkillBuilder):
        with pytest.raises(ValueError, match="description"):
            skill_builder.name("n").build()

    def test_reset_clears_state(self, skill_builder: SkillBuilder):
        skill_builder.name("review").description("Review code")
        skill_builder.reset()
        with pytest.raises(ValueError, match="name"):
            skill_builder.build()

    def test_built_skill_is_frozen(self, skill_builder: SkillBuilder):
        skill = skill_builder.name("x").description("d").build()
        with pytest.raises(AttributeError):
            skill.name = "y"  # type: ignore[misc]
