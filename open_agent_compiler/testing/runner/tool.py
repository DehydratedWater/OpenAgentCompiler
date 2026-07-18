"""ToolTest runner — drive a tool's handler (or its mock) under a scenario.

Resolution order for what the tool returns:
1. The active MockProfile's response for this tool name (if profile_lookup
   is provided and the profile covers this tool).
2. The tool's own default mock (ToolDefinition.mock from Phase 1.1).
3. The real handler — dynamically import the ScriptTool subclass from the
   tool's bundled script and call execute() with the validated input.

Path 3 is best-effort: if the script can't be loaded the runner reports
a skipped result with a clear reason instead of crashing. This matches
the philosophy from Phase 1.3 (tool_schema.derive_json_schema): missing
or broken handler scripts don't poison the testing surface.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.model.core.mock_model import MockProfile, MockResponse, MockState
from open_agent_compiler.model.core.test_model import ToolTest
from open_agent_compiler.model.core.tools_model import ToolDefinition
from open_agent_compiler.runtime import ScriptTool
from open_agent_compiler.testing.evaluation import EvaluationResult, RunContext, evaluate


class ToolRunResult(BaseModel):
    """Per-test result for one ToolTest."""

    model_config = ConfigDict(frozen=False)

    test_name: str
    tool_name: str
    passed: bool
    output: Any = None
    handler_kind: str = Field(
        default="unknown",
        description="'mock_profile' / 'tool_default_mock' / 'real_handler' / 'skipped'.",
    )
    skip_reason: str = ""
    results: list[EvaluationResult] = Field(default_factory=list)


ProfileLookup = Callable[[str], MockProfile | None]


def _resolve_mock(
    test: ToolTest, tool: ToolDefinition,
    profile_lookup: ProfileLookup | None,
) -> tuple[MockResponse | None, str]:
    if test.mock_profile and profile_lookup is not None:
        profile = profile_lookup(test.mock_profile)
        if profile is not None:
            override = profile.resolve(tool.header.name)
            if override is not None:
                return override, "mock_profile"
    if tool.mock is not None:
        return tool.mock, "tool_default_mock"
    return None, "real_handler"


def _resolve_mock_output(
    mock: MockResponse, validated_input: BaseModel,
    state: MockState | None = None,
) -> Any:
    """Resolve one mock invocation to its output dict.

    `state` carries the per-tool call_index + scratchpad across calls
    in a multi-call scenario (multi-turn AgentTest, repeated ToolTest
    invocations). For a single fresh invocation pass state=None and
    a transient state with call_index=0 is constructed for the
    'sequence' / 'stateful_callable' kinds that need it.

    The caller is expected to mutate `state.call_index += 1` AFTER
    a successful resolution so the next call resolves to the next
    sequence element. Keeping the increment external lets the runner
    reset state cleanly when a scenario reruns.
    """
    if mock.kind == "fixed":
        return mock.fixed_output
    if mock.kind == "echo":
        return validated_input.model_dump()
    if mock.kind == "callable":
        assert mock.callable_spec, "MockResponse validator enforces this"
        module_name, attr = mock.callable_spec.rsplit(":", 1)
        fn = getattr(importlib.import_module(module_name), attr)
        result = fn(validated_input)
        if isinstance(result, BaseModel):
            return result.model_dump()
        return result
    if mock.kind == "sequence":
        assert mock.sequence, "MockResponse validator enforces this"
        idx = state.call_index if state is not None else 0
        # Out-of-bounds calls reuse the last element so the scenario
        # terminates cleanly instead of crashing on call N+1.
        idx = min(idx, len(mock.sequence) - 1)
        return _resolve_mock_output(mock.sequence[idx], validated_input, state)
    if mock.kind == "stateful_callable":
        assert mock.callable_spec, "MockResponse validator enforces this"
        module_name, attr = mock.callable_spec.rsplit(":", 1)
        fn = getattr(importlib.import_module(module_name), attr)
        local_state = state if state is not None else MockState(
            tool_name="<unknown>",
        )
        result = fn(validated_input, local_state)
        if isinstance(result, BaseModel):
            return result.model_dump()
        return result
    raise ValueError(f"unknown MockResponse.kind: {mock.kind!r}")


def _load_script_tool_class(tool: ToolDefinition) -> type[ScriptTool] | None:
    """Dynamic-import the tool's handler to find its ScriptTool subclass.

    Returns None when the script can't be located/loaded — the runner
    skips with a clear reason.
    """
    if not tool.json_tool or not tool.json_tool.tool_scripts:
        return None
    for ts in tool.json_tool.tool_scripts:
        for sd in ts.scripts or ():
            source = sd.source_file_path
            if source is None or not source.exists():
                continue
            mod_name = f"_oac_tooltest_{source.stem}_{id(source)}"
            spec = importlib.util.spec_from_file_location(mod_name, str(source))
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:  # noqa: BLE001
                sys.modules.pop(mod_name, None)
                continue
            for attr in vars(module).values():
                if (
                    isinstance(attr, type)
                    and issubclass(attr, ScriptTool)
                    and attr is not ScriptTool
                    and getattr(attr, "name", None) == tool.header.name
                ):
                    return attr
    return None


def _invoke_real_handler(
    tool: ToolDefinition, input_dict: dict,
) -> tuple[Any, str | None]:
    cls = _load_script_tool_class(tool)
    if cls is None:
        return None, (
            "real handler unavailable — no loadable ScriptTool subclass"
            " found for this tool"
        )
    try:
        input_model_type = cls._get_input_type()
        validated = input_model_type.model_validate(input_dict)
        output = cls().execute(validated)
    except Exception as exc:  # noqa: BLE001
        return None, f"handler raised: {exc}"
    if isinstance(output, BaseModel):
        return output.model_dump(), None
    return output, None


def run_tool_test(
    test: ToolTest, tool: ToolDefinition,
    *, profile_lookup: ProfileLookup | None = None,
) -> ToolRunResult:
    """Execute one ToolTest against one ToolDefinition."""
    mock, source = _resolve_mock(test, tool, profile_lookup)

    if mock is not None:
        # Validate input against the tool's Pydantic model if available;
        # falls back to passing the dict through untouched when no handler
        # class exists (mock-only tools).
        cls = _load_script_tool_class(tool)
        if cls is not None:
            try:
                validated_input = cls._get_input_type().model_validate(test.input)
            except Exception as exc:  # noqa: BLE001
                return ToolRunResult(
                    test_name=test.name, tool_name=tool.header.name,
                    passed=False, handler_kind=source,
                    skip_reason=f"input validation failed: {exc}",
                )
        else:
            # Provide an empty BaseModel-shaped object for echo/callable.
            class _AdHocInput(BaseModel):
                model_config = ConfigDict(extra="allow")
            validated_input = _AdHocInput(**test.input)

        try:
            output = _resolve_mock_output(mock, validated_input)
        except Exception as exc:  # noqa: BLE001
            return ToolRunResult(
                test_name=test.name, tool_name=tool.header.name,
                passed=False, handler_kind=source,
                skip_reason=f"mock resolution failed: {exc}",
            )
    else:
        output, err = _invoke_real_handler(tool, test.input)
        if err is not None:
            return ToolRunResult(
                test_name=test.name, tool_name=tool.header.name,
                passed=False, handler_kind="skipped", skip_reason=err,
            )

    ctx = RunContext(output=output)
    results = [evaluate(ev, ctx) for ev in test.evaluators]
    passed = all(r.passed for r in results) if results else True
    return ToolRunResult(
        test_name=test.name,
        tool_name=tool.header.name,
        passed=passed,
        output=output,
        handler_kind=source,
        results=results,
    )
