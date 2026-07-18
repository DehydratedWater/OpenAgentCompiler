"""In-process interactive runner — the framework-owned tool loop.

No network and no `openai` import: every test scripts a FakeChatClient with a
fixed ChatResponse sequence and asserts on the transcript, the ToolCallRecords,
the emitted events, and the structured-output handling.
"""

from __future__ import annotations

import pytest

from open_agent_compiler.interactive.events import CollectingSink, EventKind
from open_agent_compiler.interactive.runner import (
    ChatResponse,
    ChatToolCall,
    MissingDependencyError,
    OpenAICompatClient,
    run_interactive,
)
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


TOOL = ToolSpec(
    name="priority-manager", description="manage priorities",
    input_schema={"type": "object", "properties": {"action": {"type": "string"}}},
)


class FakeChatClient:
    """Scripted ChatClient: returns the next response, records each call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, *, messages, tools=None, model, **params):
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "tools": tools, "model": model, "params": params,
        })
        return self._responses.pop(0)


def _tc(name="priority-manager", args=None, id="call-1"):
    return ChatToolCall(id=id, name=name, args=args or {"action": "audit"})


# --- plain answer -------------------------------------------------------

def test_plain_single_turn_answer():
    client = FakeChatClient([ChatResponse(content="all calm")])
    result = run_interactive(_spec(), "status?", client=client)
    assert result.output_text == "all calm"
    assert result.rounds == 1
    assert result.error is None
    assert result.tool_calls == []
    # transcript: system, user, final assistant
    assert [m["role"] for m in result.messages] == ["system", "user", "assistant"]
    assert result.messages[0]["content"] == "You steer campaigns."
    assert result.messages[1]["content"] == "status?"
    # no tools on the spec -> none offered to the model
    assert client.calls[0]["tools"] is None
    assert client.calls[0]["model"] == "qwen2.5"


def test_tools_are_offered_in_openai_function_shape():
    client = FakeChatClient([ChatResponse(content="ok")])
    run_interactive(_spec(tools=(TOOL,)), "go", client=client)
    (tool_dict,) = client.calls[0]["tools"]
    assert tool_dict["type"] == "function"
    assert tool_dict["function"]["name"] == "priority-manager"
    assert tool_dict["function"]["description"] == "manage priorities"
    assert tool_dict["function"]["parameters"] == TOOL.input_schema


def test_tool_without_input_schema_gets_permissive_object_schema():
    bare = ToolSpec(name="t", description="d")
    client = FakeChatClient([ChatResponse(content="ok")])
    run_interactive(_spec(tools=(bare,)), "go", client=client)
    params = client.calls[0]["tools"][0]["function"]["parameters"]
    assert params["type"] == "object"
    assert params["additionalProperties"] is True


# --- tool loop ----------------------------------------------------------

def test_two_round_tool_loop_records_calls_and_transcript():
    client = FakeChatClient([
        ChatResponse(tool_calls=[_tc(args={"action": "audit"}, id="c1")]),
        ChatResponse(tool_calls=[_tc(args={"action": "fix"}, id="c2")]),
        ChatResponse(content="done: audited and fixed"),
    ])
    calls = []

    def runner(name, args):
        calls.append((name, args))
        return f"ran {args['action']}"

    result = run_interactive(_spec(tools=(TOOL,)), "sort it", client=client,
                             tool_runner=runner)
    assert result.output_text == "done: audited and fixed"
    assert result.rounds == 3
    assert result.error is None
    assert calls == [
        ("priority-manager", {"action": "audit"}),
        ("priority-manager", {"action": "fix"}),
    ]
    # ToolCallRecords carry args + output, no error
    assert [(r.name, r.args, r.output, r.error) for r in result.tool_calls] == [
        ("priority-manager", {"action": "audit"}, "ran audit", None),
        ("priority-manager", {"action": "fix"}, "ran fix", None),
    ]
    # transcript: system, user, assistant(tool_calls), tool, assistant(tool_calls),
    # tool, final assistant
    assert [m["role"] for m in result.messages] == [
        "system", "user", "assistant", "tool", "assistant", "tool", "assistant",
    ]
    assert result.messages[2]["tool_calls"][0]["id"] == "c1"
    assert result.messages[3] == {"role": "tool", "tool_call_id": "c1",
                                  "content": "ran audit"}
    assert result.messages[5]["content"] == "ran fix"
    # the second completion saw the first tool result
    assert client.calls[1]["messages"][3]["content"] == "ran audit"


def test_tool_runner_error_is_recorded_and_fed_back_to_the_model():
    client = FakeChatClient([
        ChatResponse(tool_calls=[_tc(id="c1")]),
        ChatResponse(content="recovered without the tool"),
    ])

    def boom(name, args):
        raise ValueError("db unreachable")

    result = run_interactive(_spec(tools=(TOOL,)), "go", client=client,
                             tool_runner=boom)
    # recorded, not raised
    (record,) = result.tool_calls
    assert record.error == "db unreachable"
    assert record.output is None
    # error text went back to the model as the tool result
    tool_msg = client.calls[1]["messages"][3]
    assert tool_msg["role"] == "tool"
    assert "db unreachable" in tool_msg["content"]
    # and the run still completed normally
    assert result.output_text == "recovered without the tool"
    assert result.error is None


def test_max_tool_rounds_cap_records_error_when_model_still_wants_tools():
    client = FakeChatClient([
        ChatResponse(tool_calls=[_tc(id=f"c{i}")]) for i in range(3)
    ])
    result = run_interactive(_spec(tools=(TOOL,)), "go", client=client,
                             tool_runner=lambda n, a: "ok", max_tool_rounds=2)
    assert result.error == "max tool rounds reached"
    assert result.rounds == 3          # 2 tool rounds + the still-asking reply
    assert len(result.tool_calls) == 2  # only the capped rounds executed


def test_no_tool_runner_but_model_requests_tools():
    client = FakeChatClient([
        ChatResponse(content="I would call a tool here",
                     tool_calls=[_tc()]),
    ])
    result = run_interactive(_spec(tools=(TOOL,)), "go", client=client)
    assert result.error == "model requested tools but no tool_runner provided"
    assert result.output_text == "I would call a tool here"
    assert result.tool_calls == []


# --- events -------------------------------------------------------------

def test_events_emitted_to_sink_with_agent_id_source():
    sink = CollectingSink()
    client = FakeChatClient([
        ChatResponse(tool_calls=[_tc()]),
        ChatResponse(content="done"),
    ])
    run_interactive(_spec(tools=(TOOL,)), "go", client=client,
                    tool_runner=lambda n, a: "ok", sink=sink)
    assert sink.kinds() == [EventKind.TOOL_START, EventKind.TOOL_END]
    assert all(e.source == "chat" for e in sink.events)
    assert sink.events[0].payload["tool"] == "priority-manager"
    assert sink.events[1].payload["result"] == "ok"


def test_tool_failure_emits_error_event():
    sink = CollectingSink()
    client = FakeChatClient([
        ChatResponse(tool_calls=[_tc()]),
        ChatResponse(content="done"),
    ])

    def boom(name, args):
        raise RuntimeError("nope")

    run_interactive(_spec(tools=(TOOL,)), "go", client=client,
                    tool_runner=boom, sink=sink)
    assert sink.kinds() == [EventKind.TOOL_START, EventKind.TOOL_ERROR]
    assert sink.events[1].payload["error"] == "nope"


def test_emitting_runner_pushes_progress_on_the_same_stream():
    sink = CollectingSink()
    client = FakeChatClient([
        ChatResponse(tool_calls=[_tc()]),
        ChatResponse(content="done"),
    ])

    def runner(name, args, emitter):
        emitter.progress("working", current=1, total=2)
        return "ok"

    run_interactive(_spec(tools=(TOOL,)), "go", client=client,
                    tool_runner=runner, sink=sink)
    assert sink.kinds() == [
        EventKind.TOOL_START, EventKind.PROGRESS, EventKind.TOOL_END,
    ]


# --- structured output --------------------------------------------------

SCHEMA = {"type": "object", "properties": {"verdict": {"type": "string"}}}


def test_structured_output_happy_path_with_code_fences():
    client = FakeChatClient([
        ChatResponse(content='Here you go:\n```json\n{"verdict": "ship"}\n```'),
    ])
    result = run_interactive(_spec(output_schema=SCHEMA), "judge", client=client)
    assert result.structured == {"verdict": "ship"}
    assert result.error is None
    # the schema instruction is merged into the ONE leading system message —
    # strict chat templates (qwen/vLLM) reject a second system message.
    sent = client.calls[0]["messages"]
    assert sent[0]["role"] == "system"
    assert "verdict" in sent[0]["content"]
    assert sum(1 for m in sent if m["role"] == "system") == 1
    assert sent[1] == {"role": "user", "content": "judge"}


def test_structured_output_parse_failure_keeps_output_text():
    client = FakeChatClient([ChatResponse(content="sorry, no json today")])
    result = run_interactive(_spec(output_schema=SCHEMA), "judge", client=client)
    assert result.structured is None
    assert result.error is not None
    assert result.error.startswith("structured output parse failed")
    assert result.output_text == "sorry, no json today"


def test_structured_output_tolerates_trailing_prose():
    client = FakeChatClient([
        ChatResponse(content='{"verdict": "hold"} — because budget.'),
    ])
    result = run_interactive(_spec(output_schema=SCHEMA), "judge", client=client)
    assert result.structured == {"verdict": "hold"}


# --- history / message-list input --------------------------------------

def test_history_is_included_between_system_and_user_turn():
    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]
    client = FakeChatClient([ChatResponse(content="ok")])
    run_interactive(_spec(), "follow-up", client=client, history=history)
    sent = client.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "earlier question"
    assert sent[3]["content"] == "follow-up"


def test_user_input_as_message_list_is_taken_verbatim():
    turn = [
        {"role": "user", "content": "part one"},
        {"role": "user", "content": "part two"},
    ]
    client = FakeChatClient([ChatResponse(content="ok")])
    run_interactive(_spec(), turn, client=client)
    sent = client.calls[0]["messages"]
    assert sent[1:] == turn


# --- params pass-through -------------------------------------------------

def test_extra_params_are_forwarded_to_the_client():
    client = FakeChatClient([ChatResponse(content="ok")])
    run_interactive(_spec(), "go", client=client, temperature=0.9, seed=7)
    assert client.calls[0]["params"] == {"temperature": 0.9, "seed": 7}


# --- OpenAICompatClient --------------------------------------------------

def test_openai_compat_client_from_spec_assembles_defaults():
    preset = LIVE.model_copy(update={"provider_options": {
        **LIVE.provider_options,
        "extra_body": '{"chat_template_kwargs": {"enable_thinking": false}}',
    }})
    spec = InteractiveAgentSpec(agent_id="x", model=preset, system_prompt="s")
    client = OpenAICompatClient.from_spec(spec)
    assert client.default_params["temperature"] == 0.3
    assert client.default_params["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_openai_compat_client_missing_dependency(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "openai":
            raise ImportError("no openai")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    client = OpenAICompatClient(base_url="http://localhost:8000/v1", api_key="x")
    with pytest.raises(MissingDependencyError, match="pip install openai"):
        client.complete(messages=[{"role": "user", "content": "hi"}],
                        tools=None, model="qwen2.5")
