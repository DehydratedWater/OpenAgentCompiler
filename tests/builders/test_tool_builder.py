"""Tests for ToolBuilder."""

import pytest

from open_agent_compiler._types import (
    ParameterDefinition,
    StreamFormat,
)
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
        tool = (
            tool_builder.name("grep")
            .description("Search files")
            .file_path("grep.py")
            .parameter(
                ParameterDefinition(
                    name="pattern",
                    description="Regex pattern",
                    param_type="str",
                )
            )
            .build()
        )
        assert tool.name == "grep"
        assert tool.description == "Search files"
        assert tool.file_path == "grep.py"
        assert len(tool.parameters) == 1
        assert tool.parameters[0].name == "pattern"

    def test_from_script(self, tool_builder: ToolBuilder, tmp_path):
        script_path = _write_handler_script(tmp_path, name="search")
        tool = tool_builder.from_script(script_path).build()
        assert tool.name == "search"
        assert tool.description == "A test tool"
        assert tool.file_path == script_path
        assert len(tool.parameters) == 2
        names = {p.name for p in tool.parameters}
        assert names == {"query", "limit"}

    def test_from_script_stream_config(self, tool_builder: ToolBuilder, tmp_path):
        script_path = _write_handler_script(tmp_path, name="stream_tool", stream=True)
        tool = tool_builder.from_script(script_path).build()
        assert tool.stream_format == StreamFormat.TEXT
        assert tool.stream_field == "query"

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
        assert tool.file_path == "handler_tool.py"
        assert len(tool.parameters) == 1
        assert tool.parameters[0].name == "text"
        assert tool.parameters[0].param_type == "str"

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

    def test_parameter_extraction_types(self, tool_builder: ToolBuilder, tmp_path):
        script_path = _write_handler_script(tmp_path, name="typed_tool")
        tool = tool_builder.from_script(script_path).build()
        param_map = {p.name: p for p in tool.parameters}
        assert param_map["query"].param_type == "str"
        assert param_map["query"].required is True
        assert param_map["limit"].param_type == "int"
        assert param_map["limit"].required is False
        assert param_map["limit"].default == "10"

    def test_fluent_returns_self(self, tool_builder: ToolBuilder):
        assert tool_builder.name("x") is tool_builder
        assert tool_builder.description("d") is tool_builder
        assert tool_builder.file_path("f.py") is tool_builder
        assert (
            tool_builder.parameter(
                ParameterDefinition(name="p", description="d", param_type="str")
            )
            is tool_builder
        )

    def test_missing_name_raises(self, tool_builder: ToolBuilder):
        with pytest.raises(ValueError, match="name"):
            tool_builder.description("d").file_path("f.py").build()

    def test_missing_description_raises(self, tool_builder: ToolBuilder):
        with pytest.raises(ValueError, match="description"):
            tool_builder.name("n").file_path("f.py").build()

    def test_missing_file_path_raises(self, tool_builder: ToolBuilder):
        with pytest.raises(ValueError, match="file_path"):
            tool_builder.name("n").description("d").build()

    def test_invalid_stream_field_raises(self, tool_builder: ToolBuilder):
        with pytest.raises(ValueError, match="stream_field"):
            (
                tool_builder.name("n")
                .description("d")
                .file_path("f.py")
                .parameter(
                    ParameterDefinition(name="x", description="d", param_type="str")
                )
                .stream_field("nonexistent")
                .build()
            )

    def test_no_script_tool_subclass_raises(self, tool_builder: ToolBuilder, tmp_path):
        script = "x = 1\n"
        path = tmp_path / "empty.py"
        path.write_text(script)
        with pytest.raises(ImportError, match="No ScriptTool subclass"):
            tool_builder.from_script(str(path))

    def test_reset_clears_state(self, tool_builder: ToolBuilder):
        tool_builder.name("grep").description("Search").file_path("f.py")
        tool_builder.reset()
        with pytest.raises(ValueError, match="name"):
            tool_builder.build()

    def test_built_tool_is_frozen(self, tool_builder: ToolBuilder):
        tool = tool_builder.name("x").description("d").file_path("f.py").build()
        with pytest.raises(AttributeError):
            tool.name = "y"  # type: ignore[misc]
