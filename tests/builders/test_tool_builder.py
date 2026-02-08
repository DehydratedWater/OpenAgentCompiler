"""Tests for ToolBuilder."""

import pytest

from open_agent_compiler.builders import ToolBuilder


class TestToolBuilder:
    def test_build_minimal(self, tool_builder: ToolBuilder):
        tool = tool_builder.name("grep").description("Search files").build()
        assert tool.name == "grep"
        assert tool.description == "Search files"
        assert tool.parameters == {}

    def test_build_with_parameters(self, tool_builder: ToolBuilder):
        tool = (
            tool_builder.name("grep")
            .description("Search files")
            .parameter("pattern", {"type": "string"})
            .parameter("path", {"type": "string"})
            .build()
        )
        assert tool.parameters == {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        }

    def test_fluent_returns_self(self, tool_builder: ToolBuilder):
        ret = tool_builder.name("x")
        assert ret is tool_builder

    def test_missing_name_raises(self, tool_builder: ToolBuilder):
        with pytest.raises(ValueError, match="name"):
            tool_builder.description("d").build()

    def test_missing_description_raises(self, tool_builder: ToolBuilder):
        with pytest.raises(ValueError, match="description"):
            tool_builder.name("n").build()

    def test_reset_clears_state(self, tool_builder: ToolBuilder):
        tool_builder.name("grep").description("Search")
        tool_builder.reset()
        with pytest.raises(ValueError, match="name"):
            tool_builder.build()

    def test_built_tool_is_frozen(self, tool_builder: ToolBuilder):
        tool = tool_builder.name("x").description("d").build()
        with pytest.raises(AttributeError):
            tool.name = "y"  # type: ignore[misc]
