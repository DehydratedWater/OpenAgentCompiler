"""ToolTest runner: mock-profile path, default-mock path, real-handler path."""

from __future__ import annotations

from pathlib import Path


from open_agent_compiler.model.core.mock_model import MockProfile, MockResponse
from open_agent_compiler.model.core.permissions_model import BashToolPermission, JsonToolPermission
from open_agent_compiler.model.core.test_model import (
    EqualsEvaluator,
    JsonPathEvaluator,
    ToolTest,
)
from open_agent_compiler.model.core.tools_model import (
    ScriptDefinition,
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
    ToolDefinitionLogicJson,
    ToolScriptDefinition,
)
from open_agent_compiler.testing.runner.tool import run_tool_test


def _bare_tool(name: str, *, mock: MockResponse | None = None) -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name=name, description="d", usage_explanation_long="l",
            usage_explanation_short="s", rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(tool_name="bash", value="allow"),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
        ),
        mock=mock,
    )


# ---- mock_profile path --------------------------------------------------


def test_mock_profile_overrides_tool_default_mock() -> None:
    tool = _bare_tool("echo", mock=MockResponse(kind="echo"))
    profile = MockProfile(
        name="ci",
        responses={"echo": MockResponse(
            kind="fixed", fixed_output={"sent": True},
        )},
    )
    test = ToolTest(
        name="ci-mocks-out",
        input={"text": "hi"},
        mock_profile="ci",
        evaluators=(EqualsEvaluator(expected={"sent": True}),),
    )
    out = run_tool_test(test, tool, profile_lookup=lambda _: profile)
    assert out.passed
    assert out.handler_kind == "mock_profile"
    assert out.output == {"sent": True}


def test_mock_profile_without_entry_falls_back_to_default() -> None:
    tool = _bare_tool("echo", mock=MockResponse(
        kind="fixed", fixed_output={"from": "default"},
    ))
    profile = MockProfile(name="ci", responses={})  # doesn't cover 'echo'
    test = ToolTest(
        name="t", input={"text": "hi"}, mock_profile="ci",
        evaluators=(EqualsEvaluator(expected={"from": "default"}),),
    )
    out = run_tool_test(test, tool, profile_lookup=lambda _: profile)
    assert out.passed
    assert out.handler_kind == "tool_default_mock"


# ---- default mock path --------------------------------------------------


def test_tool_default_mock_used_when_no_profile() -> None:
    tool = _bare_tool("echo", mock=MockResponse(kind="echo"))
    test = ToolTest(name="t", input={"text": "hi"})  # no evaluators
    out = run_tool_test(test, tool)
    assert out.handler_kind == "tool_default_mock"
    # Echo returns the validated input dump; with no handler class
    # available, we use an ad-hoc BaseModel that preserves the input keys.
    assert out.output == {"text": "hi"}


def test_default_mock_with_json_path_evaluator_passes() -> None:
    tool = _bare_tool("query", mock=MockResponse(
        kind="fixed",
        fixed_output={"items": [{"id": "a"}, {"id": "b"}]},
    ))
    test = ToolTest(
        name="t", input={},
        evaluators=(JsonPathEvaluator(path="items.1.id", expected="b"),),
    )
    out = run_tool_test(test, tool)
    assert out.passed


# ---- real handler path --------------------------------------------------


def _emit_script_tool(tmp_path: Path) -> tuple[Path, str]:
    """Write a minimal ScriptTool to disk and return (path, tool_name)."""
    name = "minimal_test_tool"
    script = tmp_path / "tool.py"
    script.write_text(
        "from pydantic import BaseModel\n"
        "from open_agent_compiler.runtime import ScriptTool\n\n"
        "class _In(BaseModel):\n"
        "    text: str\n\n"
        "class _Out(BaseModel):\n"
        "    text: str\n"
        "    upper: str\n\n"
        f"class _Tool(ScriptTool[_In, _Out]):\n"
        f"    name = '{name}'\n"
        f"    description = 'echo upper'\n"
        f"    def execute(self, input):\n"
        f"        return _Out(text=input.text, upper=input.text.upper())\n"
    )
    return script, name


def _tool_with_real_handler(script: Path, tool_name: str) -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name=tool_name, description="d", usage_explanation_long="l",
            usage_explanation_short="s", rules=[],
        ),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(tool_name="custom_tool", value="allow"),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
            tool_scripts=[
                ToolScriptDefinition(
                    paths=[script],
                    scripts=[
                        ScriptDefinition(
                            target_file_path=script,
                            source_file_path=script,
                            source_file_type="python",
                            script_contents=None,
                        )
                    ],
                )
            ],
        ),
    )


def test_real_handler_executes_when_no_mocks(tmp_path: Path) -> None:
    script, name = _emit_script_tool(tmp_path)
    tool = _tool_with_real_handler(script, name)
    test = ToolTest(
        name="happy",
        input={"text": "hello"},
        evaluators=(
            EqualsEvaluator(field="upper", expected="HELLO"),
        ),
    )
    out = run_tool_test(test, tool)
    assert out.handler_kind == "real_handler"
    assert out.passed
    assert out.output["upper"] == "HELLO"


def test_real_handler_skips_when_script_missing() -> None:
    tool = ToolDefinition(
        header=ToolDefinitionHeader(
            name="ghost", description="d", usage_explanation_long="l",
            usage_explanation_short="s", rules=[],
        ),
        # No json_tool / scripts -> no loadable handler.
        bash_tool=None,
    )
    test = ToolTest(name="t", input={})
    out = run_tool_test(test, tool)
    assert out.handler_kind == "skipped"
    assert "real handler unavailable" in out.skip_reason


def test_mock_failure_returns_failing_result_with_reason() -> None:
    tool = _bare_tool("broken", mock=MockResponse(
        kind="callable", callable_spec="nonexistent.module:fn",
    ))
    test = ToolTest(name="t", input={})
    out = run_tool_test(test, tool)
    assert not out.passed
    assert "mock resolution failed" in out.skip_reason


def test_evaluators_failing_makes_tool_test_fail() -> None:
    tool = _bare_tool("t", mock=MockResponse(
        kind="fixed", fixed_output={"x": 1},
    ))
    test = ToolTest(
        name="t", input={},
        evaluators=(EqualsEvaluator(expected={"x": 99}),),
    )
    out = run_tool_test(test, tool)
    assert not out.passed
    assert out.results[0].passed is False
