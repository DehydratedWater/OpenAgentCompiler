"""LangChain binding — builds the live-provider chat model, tools, runnable.

No network: base_url + a dummy key make ChatOpenAI construct offline, and the
tool runner is a local stub.
"""

from __future__ import annotations

import pytest

from open_agent_compiler.interactive.bindings import langchain_binding as lcb
from open_agent_compiler.interactive.spec import InteractiveAgentSpec, ToolSpec
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults

LIVE = ModelPreset(
    name="l", provider="local", model_id="qwen2.5",
    sampling=SamplingDefaults(temperature=0.3),
    provider_options={"base_url": "http://localhost:8000/v1", "api_key_env": "LOCAL_LLM_KEY"},
)


def _spec(tools=()):
    return InteractiveAgentSpec(
        agent_id="chat", model=LIVE, system_prompt="You steer campaigns.", tools=tools,
    )


def test_chat_model_points_at_the_live_provider():
    m = lcb.build_chat_model(_spec(), api_key="dummy")
    assert m.model_name == "qwen2.5"
    assert "localhost:8000" in str(m.openai_api_base)
    assert m.temperature == 0.3
    assert m.streaming is True


def test_api_key_resolution_prefers_explicit_then_env_then_placeholder(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_KEY", raising=False)
    assert lcb._resolve_api_key(_spec(), "explicit") == "explicit"
    monkeypatch.setenv("LOCAL_LLM_KEY", "from-env")
    assert lcb._resolve_api_key(_spec(), None) == "from-env"
    monkeypatch.delenv("LOCAL_LLM_KEY", raising=False)
    assert lcb._resolve_api_key(_spec(), None) == "not-needed"


def test_tool_conversion_routes_to_runner():
    calls = []

    def runner(name, args):
        calls.append((name, args))
        return f"ran {name}"

    spec = _spec(tools=(ToolSpec(name="priority-manager", description="manage priorities"),))
    tools = lcb.to_langchain_tools(spec, runner)
    assert len(tools) == 1 and tools[0].name == "priority-manager"
    out = tools[0].invoke("audit now")
    assert out == "ran priority-manager"
    assert calls == [("priority-manager", {"input": "audit now"})]


def test_tool_without_runner_raises_clearly():
    spec = _spec(tools=(ToolSpec(name="x", description="d"),))
    tool = lcb.to_langchain_tools(spec, None)[0]
    with pytest.raises(RuntimeError, match="no tool_runner"):
        tool.invoke("go")


def test_bind_returns_runnable_with_tools_bound():
    spec = _spec(tools=(ToolSpec(name="t", description="d"),))
    runnable = lcb.bind(spec, tool_runner=lambda n, a: "ok", api_key="dummy")
    # It's an LCEL sequence (prompt | model). Just assert it composed.
    from langchain_core.runnables import Runnable
    assert isinstance(runnable, Runnable)


def test_bind_handles_json_braces_in_system_prompt():
    # System prompts routinely contain JSON examples like {"reply": ...}. The
    # binding must NOT treat those braces as template variables (regression:
    # ChatPromptTemplate f-string parsing raised on them, silently breaking the
    # live path — falling back instead of hitting the live provider).
    spec = InteractiveAgentSpec(
        agent_id="x", model=LIVE,
        system_prompt='Return strict JSON only:\n{"reply": "...", "rerun": true}',
    )
    runnable = lcb.bind(spec, api_key="dummy")  # must not raise
    prompt_step = runnable.first  # the ChatPromptTemplate
    rendered = prompt_step.invoke({"messages": [("user", "make it premium")]}).to_messages()
    assert '{"reply"' in rendered[0].content  # literal braces preserved
    assert any(getattr(m, "content", "") == "make it premium" for m in rendered)


def test_tools_emit_start_end_events_into_a_sink():
    from open_agent_compiler.interactive.events import CollectingSink, EventKind

    sink = CollectingSink()
    spec = _spec(tools=(ToolSpec(name="priority-manager", description="d"),))
    tool = lcb.to_langchain_tools(spec, lambda n, a: "done", sink=sink)[0]
    out = tool.invoke("audit now")
    assert out == "done"
    assert sink.kinds() == [EventKind.TOOL_START, EventKind.TOOL_END]
    assert sink.events[0].source == "priority-manager"
    assert sink.events[0].payload["args"] == {"input": "audit now"}
    assert sink.events[1].payload["result"] == "done"


def test_tool_failure_emits_error_event_then_reraises():
    from open_agent_compiler.interactive.events import CollectingSink, EventKind

    sink = CollectingSink()

    def boom(name, args):
        raise ValueError("nope")

    spec = _spec(tools=(ToolSpec(name="t", description="d"),))
    tool = lcb.to_langchain_tools(spec, boom, sink=sink)[0]
    with pytest.raises(Exception):  # langchain wraps, but it propagates
        tool.invoke("go")
    assert sink.kinds() == [EventKind.TOOL_START, EventKind.TOOL_ERROR]
    assert sink.events[1].payload["error"] == "nope"


def test_emitting_runner_can_push_progress_mid_run():
    from open_agent_compiler.interactive.events import CollectingSink, EventKind

    sink = CollectingSink()

    def runner_with_progress(name, args, emitter):
        emitter.progress("working", current=1, total=2)
        return "ok"

    spec = _spec(tools=(ToolSpec(name="subagent", description="d"),))
    tool = lcb.to_langchain_tools(spec, runner_with_progress, sink=sink)[0]
    tool.invoke("go")
    # start, the runner's own progress, then end — all on the same stream.
    assert sink.kinds() == [
        EventKind.TOOL_START, EventKind.PROGRESS, EventKind.TOOL_END,
    ]


def test_no_sink_means_no_events_and_unchanged_behaviour():
    spec = _spec(tools=(ToolSpec(name="t", description="d"),))
    # Identical to the pre-event path — runner called plainly, no eventing.
    tool = lcb.to_langchain_tools(spec, lambda n, a: "plain")[0]
    assert tool.invoke("go") == "plain"


def test_missing_dependency_raises_helpful_error(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "langchain_openai":
            raise ImportError("no langchain")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(lcb.MissingDependencyError, match="open-agent-compiler\\[langchain\\]"):
        lcb.build_chat_model(_spec(), api_key="x")
