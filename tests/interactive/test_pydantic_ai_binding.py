"""PydanticAI binding — the alternative realtime framework adapter.

No network: base_url + a dummy key construct offline; the tool runner is
a local stub. Mirrors the LangChain binding tests one-for-one where the
semantics are shared (runner routing, events, missing-dep error).
"""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic_ai")

from open_agent_compiler.interactive.bindings import pydantic_ai_binding as pab
from open_agent_compiler.interactive.spec import InteractiveAgentSpec, ToolSpec
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults

LIVE = ModelPreset(
    name="l", provider="local", model_id="qwen2.5",
    sampling=SamplingDefaults(temperature=0.3),
    provider_options={"base_url": "http://localhost:8000/v1", "api_key_env": "LOCAL_LLM_KEY"},
)


def _spec(tools=(), output_schema=None):
    return InteractiveAgentSpec(
        agent_id="chat", model=LIVE, system_prompt="You steer campaigns.",
        tools=tools, output_schema=output_schema,
    )


def test_model_points_at_the_live_provider():
    model = pab.build_model(_spec(), api_key="dummy")
    assert model.model_name == "qwen2.5"
    assert "localhost:8000" in str(model.base_url)


def test_api_key_resolution_prefers_explicit_then_env_then_placeholder(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_KEY", raising=False)
    assert pab._resolve_api_key(_spec(), "explicit") == "explicit"
    monkeypatch.setenv("LOCAL_LLM_KEY", "from-env")
    assert pab._resolve_api_key(_spec(), None) == "from-env"
    monkeypatch.delenv("LOCAL_LLM_KEY", raising=False)
    assert pab._resolve_api_key(_spec(), None) == "not-needed"


def test_tool_conversion_routes_to_runner():
    calls = []

    def runner(name, args):
        calls.append((name, args))
        return f"ran {name}"

    spec = _spec(tools=(ToolSpec(name="priority-manager", description="manage priorities"),))
    tools = pab.to_pydantic_ai_tools(spec, runner)
    assert len(tools) == 1 and tools[0].name == "priority-manager"
    out = tools[0].function("audit now")
    assert out == "ran priority-manager"
    assert calls == [("priority-manager", {"input": "audit now"})]


def test_tool_without_runner_raises_clearly():
    spec = _spec(tools=(ToolSpec(name="x", description="d"),))
    tool = pab.to_pydantic_ai_tools(spec, None)[0]
    with pytest.raises(RuntimeError, match="no tool_runner"):
        tool.function("go")


def test_bind_returns_agent_with_temperature_settings():
    import pydantic_ai

    spec = _spec(tools=(ToolSpec(name="t", description="d"),))
    agent = pab.bind(spec, tool_runner=lambda n, a: "ok", api_key="dummy")
    assert isinstance(agent, pydantic_ai.Agent)
    assert agent.model_settings == {"temperature": 0.3}


def test_output_schema_falls_back_to_prompt_instruction():
    spec = _spec(output_schema={"type": "object", "properties": {"intent": {"type": "string"}}})
    agent = pab.bind(spec, api_key="dummy")
    assert any("JSON schema" in s for s in agent._system_prompts)


def test_native_output_type_skips_prompt_instruction():
    from pydantic import BaseModel

    class Intent(BaseModel):
        intent: str

    spec = _spec(output_schema={"type": "object"})
    agent = pab.bind(spec, api_key="dummy", output_type=Intent)
    assert all("JSON schema" not in s for s in agent._system_prompts)


def test_tools_emit_start_end_events_into_a_sink():
    from open_agent_compiler.interactive.events import CollectingSink, EventKind

    sink = CollectingSink()
    spec = _spec(tools=(ToolSpec(name="priority-manager", description="d"),))
    tool = pab.to_pydantic_ai_tools(spec, lambda n, a: "done", sink=sink)[0]
    assert tool.function("audit now") == "done"
    assert sink.kinds() == [EventKind.TOOL_START, EventKind.TOOL_END]
    assert sink.events[0].source == "priority-manager"


def test_tool_failure_emits_error_event_then_reraises():
    from open_agent_compiler.interactive.events import CollectingSink, EventKind

    sink = CollectingSink()

    def boom(name, args):
        raise ValueError("nope")

    spec = _spec(tools=(ToolSpec(name="t", description="d"),))
    tool = pab.to_pydantic_ai_tools(spec, boom, sink=sink)[0]
    with pytest.raises(ValueError):
        tool.function("go")
    assert sink.kinds() == [EventKind.TOOL_START, EventKind.TOOL_ERROR]


def test_emitting_runner_can_push_progress_mid_run():
    from open_agent_compiler.interactive.events import CollectingSink, EventKind

    sink = CollectingSink()

    def runner_with_progress(name, args, emitter):
        emitter.progress("working", current=1, total=2)
        return "ok"

    spec = _spec(tools=(ToolSpec(name="subagent", description="d"),))
    tool = pab.to_pydantic_ai_tools(spec, runner_with_progress, sink=sink)[0]
    tool.function("go")
    assert sink.kinds() == [
        EventKind.TOOL_START, EventKind.PROGRESS, EventKind.TOOL_END,
    ]


def test_missing_dependency_raises_helpful_error(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("pydantic_ai"):
            raise ImportError("no pydantic-ai")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(pab.MissingDependencyError, match="open-agent-compiler\\[pydantic-ai\\]"):
        pab.build_model(_spec(), api_key="x")
