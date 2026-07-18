"""Mock surface: MockResponse + MockProfile + ToolDefinition.mock field."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from open_agent_compiler.model.core.mock_model import MockProfile, MockResponse
from open_agent_compiler.model.core.permissions_model import BashToolPermission
from open_agent_compiler.model.core.tools_model import (
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
)
from open_agent_compiler.runtime import MOCK_ENV, ScriptTool


def test_fixed_mock_requires_output() -> None:
    with pytest.raises(ValueError, match="requires fixed_output"):
        MockResponse(kind="fixed")


def test_callable_mock_requires_spec() -> None:
    with pytest.raises(ValueError, match="requires callable_spec"):
        MockResponse(kind="callable")


def test_callable_mock_validates_spec_shape() -> None:
    with pytest.raises(ValueError, match="must be 'module:callable'"):
        MockResponse(kind="callable", callable_spec="no_colon")


def test_echo_mock_passes() -> None:
    m = MockResponse(kind="echo")
    assert m.kind == "echo"
    assert m.fixed_output is None


def test_profile_resolves_by_tool_name() -> None:
    profile = MockProfile(
        name="prod-tests",
        responses={
            "send-message": MockResponse(kind="fixed", fixed_output={"sent": True}),
        },
    )
    assert profile.resolve("send-message").fixed_output == {"sent": True}
    assert profile.resolve("missing-tool") is None


def test_tool_definition_carries_optional_default_mock() -> None:
    tool = ToolDefinition(
        header=ToolDefinitionHeader(
            name="echo-tool",
            description="echoes input",
            usage_explanation_long="long",
            usage_explanation_short="short",
            rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(tool_name="bash", value="allow"),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
        ),
        mock=MockResponse(kind="echo"),
    )
    assert tool.mock.kind == "echo"


# ---- runtime --mock integration -------------------------------------------


class _In(BaseModel):
    text: str = Field(description="input text")


class _Out(BaseModel):
    text: str
    real_call: bool = True


class _RealTool(ScriptTool[_In, _Out]):
    name = "real-tool"
    description = "Echoes input via real execute."

    def execute(self, input: _In) -> _Out:
        return _Out(text=input.text, real_call=True)


class _MockingTool(ScriptTool[_In, _Out]):
    name = "mocking-tool"
    description = "Has a built-in mock_response override."

    def execute(self, input: _In) -> _Out:
        return _Out(text=f"REAL:{input.text}", real_call=True)

    def mock_response(self, input: _In) -> _Out:
        return _Out(text=f"MOCK:{input.text}", real_call=False)


def test_mock_response_default_returns_none() -> None:
    assert _RealTool().mock_response(_In(text="x")) is None


def test_mock_response_override_short_circuits_execute() -> None:
    out = _MockingTool().mock_response(_In(text="hi"))
    assert out.text == "MOCK:hi"
    assert out.real_call is False


def _run_script_subprocess(
    script_path: Path, args: list[str], env_overrides: dict[str, str] | None = None
) -> dict:
    env = {**os.environ, **(env_overrides or {})}
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(script_path), *args],
        env={**env, "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip())


def _emit_tool_script(tmp_path: Path) -> Path:
    """Write a minimal ScriptTool to disk so we can invoke its CLI."""
    script = tmp_path / "minimal_tool.py"
    script.write_text(
        "from pydantic import BaseModel, Field\n"
        "from open_agent_compiler.runtime import ScriptTool\n\n"
        "class _In(BaseModel):\n"
        "    text: str\n\n"
        "class _Out(BaseModel):\n"
        "    text: str\n"
        "    real_call: bool = True\n\n"
        "class T(ScriptTool[_In, _Out]):\n"
        "    name = 'mt'\n"
        "    description = 'minimal'\n"
        "    def execute(self, input):\n"
        "        return _Out(text=f'REAL:{input.text}', real_call=True)\n\n"
        "if __name__ == '__main__':\n"
        "    T.run()\n"
    )
    return script


def test_runtime_mock_env_overrides_execute(tmp_path: Path) -> None:
    script = _emit_tool_script(tmp_path)
    out = _run_script_subprocess(
        script,
        ["--text", "hi"],
        env_overrides={MOCK_ENV: json.dumps({"text": "MOCKED:hi", "real_call": False})},
    )
    assert out == {"text": "MOCKED:hi", "real_call": False}


def test_runtime_mock_flag_echo(tmp_path: Path) -> None:
    script = _emit_tool_script(tmp_path)
    out = _run_script_subprocess(script, ["--text", "ping", "--mock", "echo"])
    assert out == {"text": "ping"}


def test_runtime_real_call_when_no_mock(tmp_path: Path) -> None:
    script = _emit_tool_script(tmp_path)
    out = _run_script_subprocess(script, ["--text", "ping"])
    assert out == {"text": "REAL:ping", "real_call": True}


# ---- Phase 11: sequence + stateful_callable MockResponse kinds -------


def test_mock_sequence_requires_non_empty_sequence() -> None:
    with pytest.raises(ValueError, match="non-empty sequence"):
        MockResponse(kind="sequence", sequence=())


def test_mock_sequence_accepts_list_of_per_call_responses() -> None:
    seq = MockResponse(
        kind="sequence",
        sequence=(
            MockResponse(kind="fixed", fixed_output={"call": 1}),
            MockResponse(kind="fixed", fixed_output={"call": 2}),
        ),
    )
    assert len(seq.sequence) == 2
    assert seq.sequence[1].fixed_output == {"call": 2}


def test_mock_stateful_callable_requires_callable_spec() -> None:
    with pytest.raises(ValueError, match="stateful_callable.*callable_spec"):
        MockResponse(kind="stateful_callable")


def test_mock_stateful_callable_requires_module_colon_fn_form() -> None:
    with pytest.raises(ValueError, match="module:callable"):
        MockResponse(kind="stateful_callable", callable_spec="no_colon_here")


def test_mock_state_default_values() -> None:
    from open_agent_compiler.model.core.mock_model import MockState
    s = MockState(tool_name="my-tool")
    assert s.call_index == 0
    assert s.scratchpad == {}


def test_mock_state_scratchpad_is_writable() -> None:
    """MockState is not frozen — stateful_callable can mutate scratchpad."""
    from open_agent_compiler.model.core.mock_model import MockState
    s = MockState(tool_name="x")
    s.scratchpad["last_seen"] = "value-A"
    s.call_index = 1
    assert s.scratchpad["last_seen"] == "value-A"
    assert s.call_index == 1


def test_resolver_sequence_advances_through_state() -> None:
    """Calling the resolver with state.call_index=N picks sequence[N]."""
    from pydantic import BaseModel as _BM
    from open_agent_compiler.model.core.mock_model import MockState
    from open_agent_compiler.testing.runner.tool import _resolve_mock_output

    class _Empty(_BM):
        pass

    seq = MockResponse(
        kind="sequence",
        sequence=(
            MockResponse(kind="fixed", fixed_output={"i": 0}),
            MockResponse(kind="fixed", fixed_output={"i": 1}),
            MockResponse(kind="fixed", fixed_output={"i": 2}),
        ),
    )
    state = MockState(tool_name="x")
    assert _resolve_mock_output(seq, _Empty(), state) == {"i": 0}
    state.call_index = 1
    assert _resolve_mock_output(seq, _Empty(), state) == {"i": 1}
    state.call_index = 2
    assert _resolve_mock_output(seq, _Empty(), state) == {"i": 2}


def test_resolver_sequence_out_of_bounds_reuses_last_element() -> None:
    """Calling past the sequence length yields the final element repeatedly."""
    from pydantic import BaseModel as _BM
    from open_agent_compiler.model.core.mock_model import MockState
    from open_agent_compiler.testing.runner.tool import _resolve_mock_output

    class _Empty(_BM):
        pass

    seq = MockResponse(
        kind="sequence",
        sequence=(
            MockResponse(kind="fixed", fixed_output={"i": 0}),
            MockResponse(kind="fixed", fixed_output={"final": True}),
        ),
    )
    state = MockState(tool_name="x", call_index=99)
    assert _resolve_mock_output(seq, _Empty(), state) == {"final": True}


# Helper for stateful_callable resolver test — fn(input, state) shape.
def _stateful_demo(input, state):
    """Increments a counter in the scratchpad and returns it."""
    state.scratchpad["count"] = state.scratchpad.get("count", 0) + 1
    return {"count": state.scratchpad["count"]}


def test_resolver_stateful_callable_persists_scratchpad_across_calls() -> None:
    from pydantic import BaseModel as _BM
    from open_agent_compiler.model.core.mock_model import MockState
    from open_agent_compiler.testing.runner.tool import _resolve_mock_output

    class _Empty(_BM):
        pass

    mock = MockResponse(
        kind="stateful_callable",
        callable_spec=f"{__name__}:_stateful_demo",
    )
    state = MockState(tool_name="counter")
    out1 = _resolve_mock_output(mock, _Empty(), state)
    out2 = _resolve_mock_output(mock, _Empty(), state)
    out3 = _resolve_mock_output(mock, _Empty(), state)
    assert out1 == {"count": 1}
    assert out2 == {"count": 2}
    assert out3 == {"count": 3}
