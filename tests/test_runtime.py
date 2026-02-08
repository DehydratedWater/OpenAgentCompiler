"""Tests for the ScriptTool runtime base class."""

import json
from io import StringIO
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from open_agent_compiler._types import StreamFormat
from open_agent_compiler.runtime import ScriptTool


class SampleInput(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, description="Max results")


class SampleOutput(BaseModel):
    results: list[str] = Field(default_factory=list)
    count: int = 0


class SampleTool(ScriptTool[SampleInput, SampleOutput]):
    name = "sample"
    description = "A sample tool"

    def execute(self, input: SampleInput) -> SampleOutput:
        return SampleOutput(results=[input.query], count=1)


class StreamTool(ScriptTool[SampleInput, SampleOutput]):
    name = "stream_sample"
    description = "A streaming tool"
    stream_format = StreamFormat.TEXT
    stream_field = "query"

    def execute(self, input: SampleInput) -> SampleOutput:
        return SampleOutput(results=[input.query], count=1)


class TestGetTypes:
    def test_get_input_type(self):
        assert SampleTool._get_input_type() is SampleInput

    def test_get_output_type(self):
        assert SampleTool._get_output_type() is SampleOutput

    def test_unparameterised_raises(self):
        class BadTool(ScriptTool):  # type: ignore[type-arg]
            name = "bad"
            description = "bad"

            def execute(self, input):  # type: ignore[override]
                return None

        with pytest.raises(TypeError, match="must parameterise"):
            BadTool._get_input_type()

        with pytest.raises(TypeError, match="must parameterise"):
            BadTool._get_output_type()


class TestBuildArgparse:
    def test_argparse_has_expected_args(self):
        parser = SampleTool._build_argparse()
        # Should parse valid args without error
        args = parser.parse_args(["--query", "hello", "--limit", "5"])
        assert args.query == "hello"
        assert args.limit == 5

    def test_argparse_default_values(self):
        parser = SampleTool._build_argparse()
        args = parser.parse_args(["--query", "test"])
        assert args.query == "test"
        assert args.limit == 10

    def test_argparse_json_flag(self):
        parser = SampleTool._build_argparse()
        # --query is required, so provide it along with --json
        args = parser.parse_args(["--json", "--query", "test"])
        assert args.json_mode is True


class TestBoolField:
    def test_bool_argparse(self):
        class BoolInput(BaseModel):
            verbose: bool = Field(default=False, description="Verbose output")

        class BoolOutput(BaseModel):
            ok: bool = True

        class BoolTool(ScriptTool[BoolInput, BoolOutput]):
            name = "bool_tool"
            description = "Test bool"

            def execute(self, input: BoolInput) -> BoolOutput:
                return BoolOutput(ok=input.verbose)

        parser = BoolTool._build_argparse()
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True

        args2 = parser.parse_args(["--no-verbose"])
        assert args2.verbose is False


class TestRun:
    @patch("open_agent_compiler.runtime.load_dotenv")
    def test_run_cli_args(self, mock_dotenv, capsys):
        with (
            patch("sys.argv", ["sample", "--query", "hello", "--limit", "5"]),
            patch("sys.stdin") as mock_stdin,
        ):
            mock_stdin.isatty.return_value = True
            SampleTool.run()

        mock_dotenv.assert_called_once()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["results"] == ["hello"]
        assert output["count"] == 1

    @patch("open_agent_compiler.runtime.load_dotenv")
    def test_run_json_stdin(self, mock_dotenv, capsys):
        json_input = json.dumps({"query": "from_json", "limit": 3})
        with (
            patch("sys.argv", ["sample", "--json"]),
            patch("sys.stdin", new=StringIO(json_input)),
        ):
            SampleTool.run()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["results"] == ["from_json"]

    @patch("open_agent_compiler.runtime.load_dotenv")
    def test_run_stream_field_stdin(self, mock_dotenv, capsys):
        with (
            patch("sys.argv", ["stream_sample", "--limit", "5"]),
            patch("sys.stdin", new=StringIO("SELECT 1")),
        ):
            StreamTool.run()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["results"] == ["SELECT 1"]

    @patch("open_agent_compiler.runtime.load_dotenv")
    def test_run_missing_required_field(self, mock_dotenv):
        from pydantic import ValidationError

        with patch("sys.argv", ["sample"]), patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            with pytest.raises(ValidationError):
                SampleTool.run()
