"""LangChain binding for the interactive target.

Turns an `InteractiveAgentSpec` into LangChain pieces pointed at the *live*
provider (e.g. a local OpenAI-compatible qwen — NOT the worker provider).
Kept thin on purpose: it builds the streaming chat model, converts the spec's
tools to LangChain tools (with a pluggable runner), and wires a standard LCEL
runnable. For a full tool-calling loop the consumer drops these into their own
LangGraph / AgentExecutor — that orchestration layer is theirs, not the
framework's.

`langchain-openai` is an optional extra (`pip install
open-agent-compiler[langchain]`); it is imported lazily so the core framework
stays dependency-light.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from open_agent_compiler.interactive.events import (
    EventEmitter,
    EventSink,
    as_sink,
    invoke_runner,
)
from open_agent_compiler.interactive.spec import InteractiveAgentSpec, ToolSpec

# (tool_name, args_dict) -> result text. The consumer wires execution
# (subprocess to the ScriptTool, an API call, etc.). None of the framework's
# business — it just routes the model's tool call to the runner. A runner may
# optionally widen to (tool_name, args_dict, emitter) to emit mid-run progress
# (see `open_agent_compiler.interactive.events.invoke_runner`).
ToolRunner = Callable[..., str]


class MissingDependencyError(RuntimeError):
    pass


def _require(modname: str):
    try:
        return __import__(modname, fromlist=["_"])
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise MissingDependencyError(
            f"the LangChain binding needs '{modname}'. Install the extra: "
            "pip install open-agent-compiler[langchain]"
        ) from exc


def _resolve_api_key(spec: InteractiveAgentSpec, api_key: str | None) -> str:
    if api_key:
        return api_key
    env = spec.api_key_env
    if env and os.environ.get(env):
        return os.environ[env]
    # Many local OpenAI-compatible servers ignore the key; send a placeholder
    # rather than letting the client raise on construction.
    return "not-needed"


def build_chat_model(
    spec: InteractiveAgentSpec,
    *,
    api_key: str | None = None,
    streaming: bool = True,
    **overrides: Any,
):
    """Construct a streaming ChatOpenAI bound to the spec's LIVE provider."""
    langchain_openai = _require("langchain_openai")
    ChatOpenAI = langchain_openai.ChatOpenAI
    kwargs: dict[str, Any] = {
        "model": spec.model_id,
        "api_key": _resolve_api_key(spec, api_key),
        "streaming": streaming,
    }
    if spec.base_url:
        kwargs["base_url"] = spec.base_url
    if spec.temperature is not None:
        kwargs["temperature"] = spec.temperature
    kwargs.update(overrides)
    return ChatOpenAI(**kwargs)


def _make_tool(
    tool: ToolSpec,
    runner: ToolRunner | None,
    sink: EventSink | None = None,
):
    langchain_core_tools = _require("langchain_core.tools")
    Tool = langchain_core_tools.Tool

    def _call(query: str) -> str:
        if runner is None:
            raise RuntimeError(
                f"tool '{tool.name}' was called but no tool_runner is configured"
            )
        # Best-effort arg shape: pass the raw query under 'input'. Bindings with
        # a richer input_schema can override by supplying their own runner.
        args = {"input": query}
        if sink is None:
            return runner(tool.name, args)
        # Eventing on: bracket the call with tool.start/end/error and hand the
        # runner an emitter so it (or a subagent it dispatches) can emit
        # progress on the same stream.
        emitter = EventEmitter(sink, source=tool.name)
        emitter.tool_start(args=args)
        try:
            result = invoke_runner(runner, tool.name, args, emitter)
        except Exception as exc:  # surface the failure as an event, then re-raise
            emitter.tool_error(error=str(exc))
            raise
        emitter.tool_end(result=str(result))
        return result

    return Tool(name=tool.name, description=tool.description, func=_call)


def to_langchain_tools(
    spec: InteractiveAgentSpec,
    runner: ToolRunner | None = None,
    *,
    sink: EventSink | Callable[[Any], None] | None = None,
):
    """Convert the spec's tools to LangChain tools.

    When ``sink`` is given, each tool emits ``tool.start``/``tool.end``/
    ``tool.error`` events and the runner is offered an :class:`EventEmitter`
    (if its signature accepts one) for mid-run progress. With no sink the tools
    behave exactly as before — zero overhead, no behavioural change.
    """
    resolved = None if sink is None else as_sink(sink)
    return [_make_tool(t, runner, resolved) for t in spec.tools]


def bind(
    spec: InteractiveAgentSpec,
    *,
    tool_runner: ToolRunner | None = None,
    api_key: str | None = None,
    streaming: bool = True,
    sink: EventSink | Callable[[Any], None] | None = None,
):
    """Build an LCEL runnable: prompt(system + messages) | chat model (+tools).

    Invoke/stream with `{"messages": [...]}`. Returns the runnable; the chat
    model and tools are also reachable via `.first`/`bind_tools` if the
    consumer wants to assemble their own agent loop.

    Pass ``sink`` to surface tool/subagent events on a stream (see
    `to_langchain_tools`); omit it for the plain, eventless runnable.
    """
    prompts = _require("langchain_core.prompts")
    messages_mod = _require("langchain_core.messages")
    ChatPromptTemplate = prompts.ChatPromptTemplate
    MessagesPlaceholder = prompts.MessagesPlaceholder
    SystemMessage = messages_mod.SystemMessage

    model = build_chat_model(spec, api_key=api_key, streaming=streaming)
    tools = to_langchain_tools(spec, tool_runner, sink=sink)
    if tools:
        model = model.bind_tools(tools)

    # Use a LITERAL SystemMessage, not a ("system", str) template entry — the
    # system prompt routinely contains JSON examples with `{ }`, which the
    # f-string template parser would mis-read as template variables and reject.
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=spec.system_prompt),
        MessagesPlaceholder("messages"),
    ])
    return prompt | model
