"""Tests for ToolBuilder."""

import pytest

from open_agent_compiler._types import ActionDefinition
from open_agent_compiler.builders import ToolBuilder


def _write_handler_script(tmp_path, *, name="my_tool", stream=False):
    """Write a minimal ScriptTool handler script to tmp_path and return the path."""
    stream_lines = ""
    if stream:
        stream_lines = (
            '    stream_format = StreamFormat.TEXT\n    stream_field = "query"\n'
        )

    script = (
        "from pydantic import BaseModel, Field\n"
        "from open_agent_compiler.runtime import ScriptTool, StreamFormat\n"
        "\n"
        "class Input(BaseModel):\n"
        '    query: str = Field(description="Search query")\n'
        '    limit: int = Field(default=10, description="Max results")\n'
        "\n"
        "class Output(BaseModel):\n"
        "    results: list[str] = Field(default_factory=list)\n"
        "\n"
        "class MyTool(ScriptTool[Input, Output]):\n"
        f'    name = "{name}"\n'
        '    description = "A test tool"\n'
        f"{stream_lines}"
        "\n"
        "    def execute(self, input: Input) -> Output:\n"
        "        return Output(results=[])\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    MyTool.run()\n"
    )
    path = tmp_path / f"{name}.py"
    path.write_text(script)
    return str(path)


class TestToolBuilder:
    def test_build_manual(self, tool_builder: ToolBuilder):
        action = ActionDefinition(
            command_pattern="uv run scripts/grep.py *",
            description="Search files for patterns",
            usage_example='uv run scripts/grep.py --pattern "<str>"',
        )
        tool = (
            tool_builder.name("grep").description("Search files").action(action).build()
        )
        assert tool.name == "grep"
        assert tool.description == "Search files"
        assert len(tool.actions) == 1
        assert tool.actions[0].command_pattern == "uv run scripts/grep.py *"

    def test_from_script(self, tool_builder: ToolBuilder, tmp_path):
        script_path = _write_handler_script(tmp_path, name="search")
        tool = tool_builder.from_script(script_path).build()
        assert tool.name == "search"
        assert tool.description == "A test tool"
        assert len(tool.actions) == 1
        assert tool.actions[0].command_pattern == "uv run scripts/search.py *"
        assert "search.py" in tool.script_files

    def test_from_script_stream_config(self, tool_builder: ToolBuilder, tmp_path):
        script_path = _write_handler_script(tmp_path, name="stream_tool", stream=True)
        tool = tool_builder.from_script(script_path).build()
        assert "stdin streaming" in tool.actions[0].description
        assert "stdin as text" in tool.actions[0].description

    def test_from_handler(self, tool_builder: ToolBuilder):
        from pydantic import BaseModel, Field

        from open_agent_compiler.runtime import ScriptTool

        class HInput(BaseModel):
            text: str = Field(description="Input text")

        class HOutput(BaseModel):
            length: int = 0

        class HandlerTool(ScriptTool[HInput, HOutput]):
            name = "handler_tool"
            description = "A handler tool"

            def execute(self, input: HInput) -> HOutput:
                return HOutput(length=len(input.text))

        tool = tool_builder.from_handler(HandlerTool, "handler_tool.py").build()
        assert tool.name == "handler_tool"
        assert len(tool.actions) == 1
        assert "handler_tool.py" in tool.script_files
        assert "--text" in tool.actions[0].usage_example

    def test_manual_override_after_introspection(
        self, tool_builder: ToolBuilder, tmp_path
    ):
        script_path = _write_handler_script(tmp_path, name="original")
        tool = (
            tool_builder.from_script(script_path)
            .name("overridden")
            .description("Custom description")
            .build()
        )
        assert tool.name == "overridden"
        assert tool.description == "Custom description"

    def test_script_file_method(self, tool_builder: ToolBuilder):
        action = ActionDefinition(
            command_pattern="uv run scripts/x.py *",
            description="Do X",
            usage_example="uv run scripts/x.py",
        )
        tool = (
            tool_builder.name("x")
            .description("d")
            .action(action)
            .script_file("x.py")
            .build()
        )
        assert "x.py" in tool.script_files

    def test_fluent_returns_self(self, tool_builder: ToolBuilder):
        assert tool_builder.name("x") is tool_builder
        assert tool_builder.description("d") is tool_builder
        action = ActionDefinition(
            command_pattern="*", description="d", usage_example="x"
        )
        assert tool_builder.action(action) is tool_builder
        assert tool_builder.script_file("f.py") is tool_builder

    def test_missing_name_raises(self, tool_builder: ToolBuilder):
        action = ActionDefinition(
            command_pattern="*", description="d", usage_example="x"
        )
        with pytest.raises(ValueError, match="name"):
            tool_builder.description("d").action(action).build()

    def test_missing_description_raises(self, tool_builder: ToolBuilder):
        action = ActionDefinition(
            command_pattern="*", description="d", usage_example="x"
        )
        with pytest.raises(ValueError, match="description"):
            tool_builder.name("n").action(action).build()

    def test_missing_action_raises(self, tool_builder: ToolBuilder):
        with pytest.raises(ValueError, match="action"):
            tool_builder.name("n").description("d").build()

    def test_no_script_tool_subclass_raises(self, tool_builder: ToolBuilder, tmp_path):
        script = "x = 1\n"
        path = tmp_path / "empty.py"
        path.write_text(script)
        with pytest.raises(ImportError, match="No ScriptTool subclass"):
            tool_builder.from_script(str(path))

    def test_reset_clears_state(self, tool_builder: ToolBuilder):
        action = ActionDefinition(
            command_pattern="*", description="d", usage_example="x"
        )
        tool_builder.name("grep").description("Search").action(action)
        tool_builder.reset()
        with pytest.raises(ValueError, match="name"):
            tool_builder.build()

    def test_built_tool_is_frozen(self, tool_builder: ToolBuilder):
        action = ActionDefinition(
            command_pattern="*", description="d", usage_example="x"
        )
        tool = tool_builder.name("x").description("d").action(action).build()
        with pytest.raises(AttributeError):
            tool.name = "y"  # type: ignore[misc]
