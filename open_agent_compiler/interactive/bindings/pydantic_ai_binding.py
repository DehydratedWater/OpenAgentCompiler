"""PydanticAI binding for the interactive target.

The alternative realtime framework to the LangChain binding — same
`InteractiveAgentSpec` in, a `pydantic_ai.Agent` out, pointed at the
*live* provider. Kept just as thin: build the OpenAI-compatible model,
convert the spec's tools (routed to the same pluggable `ToolRunner`
contract), assemble the Agent. Orchestration beyond one agent —
graphs, multi-agent handoffs — stays the consumer's.

`pydantic-ai` is an optional extra (`pip install
open-agent-compiler[pydantic-ai]`); imported lazily so the core
framework stays dependency-light.

Structured output: PydanticAI's native `output_type` takes a Python
type, not a JSON schema — pass `output_type=` through when you have the
model class (the better path). When only `spec.output_schema` (a JSON
schema dict) is set, the same JSON-instruction fallback as
`run_interactive` is merged into the system prompt instead.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from open_agent_compiler.interactive.events import (
    EventEmitter,
    EventSink,
    as_sink,
    invoke_runner,
)
from open_agent_compiler.interactive.spec import InteractiveAgentSpec, ToolSpec

# Same contract as the LangChain binding: (tool_name, args_dict) -> result
# text; may widen to (tool_name, args_dict, emitter) for mid-run progress.
ToolRunner = Callable[..., str]


class MissingDependencyError(RuntimeError):
    pass


def _require(modname: str):
    try:
        return __import__(modname, fromlist=["_"])
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise MissingDependencyError(
            f"the PydanticAI binding needs '{modname}'. Install the extra: "
            "pip install open-agent-compiler[pydantic-ai]"
        ) from exc


def _resolve_api_key(spec: InteractiveAgentSpec, api_key: str | None) -> str:
    if api_key:
        return api_key
    env = spec.api_key_env
    if env and os.environ.get(env):
        return os.environ[env]
    # Local OpenAI-compatible servers ignore the key; send a placeholder.
    return "not-needed"


def build_model(spec: InteractiveAgentSpec, *, api_key: str | None = None):
    """Construct an OpenAI-compatible PydanticAI model bound to the spec's
    LIVE provider (base_url from the preset's provider_options)."""
    models_openai = _require("pydantic_ai.models.openai")
    providers_openai = _require("pydantic_ai.providers.openai")
    provider = providers_openai.OpenAIProvider(
        base_url=spec.base_url,
        api_key=_resolve_api_key(spec, api_key),
    )
    return models_openai.OpenAIChatModel(spec.model_id, provider=provider)


def _make_tool(
    tool: ToolSpec,
    runner: ToolRunner | None,
    sink: EventSink | None = None,
):
    pydantic_ai = _require("pydantic_ai")
    Tool = pydantic_ai.Tool

    def _call(input: str) -> str:
        """Best-effort arg shape, mirroring the LangChain binding: the raw
        query under 'input'. Richer schemas → supply your own tools."""
        if runner is None:
            raise RuntimeError(
                f"tool '{tool.name}' was called but no tool_runner is configured"
            )
        args = {"input": input}
        if sink is None:
            return runner(tool.name, args)
        emitter = EventEmitter(sink, source=tool.name)
        emitter.tool_start(args=args)
        try:
            result = invoke_runner(runner, tool.name, args, emitter)
        except Exception as exc:  # surface as an event, then re-raise
            emitter.tool_error(error=str(exc))
            raise
        emitter.tool_end(result=str(result))
        return result

    return Tool(_call, name=tool.name, description=tool.description)


def to_pydantic_ai_tools(
    spec: InteractiveAgentSpec,
    runner: ToolRunner | None = None,
    *,
    sink: EventSink | Callable[[Any], None] | None = None,
):
    """Convert the spec's tools to PydanticAI Tools.

    With ``sink`` set, each call is bracketed with tool.start/tool.end/
    tool.error events and the runner may accept an EventEmitter for
    mid-run progress — identical semantics to the LangChain binding.
    """
    resolved = None if sink is None else as_sink(sink)
    return [_make_tool(t, runner, resolved) for t in spec.tools]


def bind(
    spec: InteractiveAgentSpec,
    *,
    tool_runner: ToolRunner | None = None,
    api_key: str | None = None,
    output_type: Any = None,
    sink: EventSink | Callable[[Any], None] | None = None,
    **agent_kwargs: Any,
):
    """Build a ready `pydantic_ai.Agent` for the spec.

    Run it with `agent.run_sync("...")` / `await agent.run("...")` /
    `agent.run_stream("...")`. `output_type` (a Python/Pydantic type)
    enables PydanticAI's native structured output; without it, a
    `spec.output_schema` JSON schema falls back to a merged prompt
    instruction. Extra `agent_kwargs` pass straight to `Agent(...)`.
    """
    pydantic_ai = _require("pydantic_ai")
    Agent = pydantic_ai.Agent

    system = spec.system_prompt
    if output_type is None and spec.output_schema is not None:
        system += (
            "\n\nAnswer with a single JSON object matching this JSON schema "
            "(no prose outside the JSON):\n" + json.dumps(spec.output_schema)
        )

    model = build_model(spec, api_key=api_key)
    tools = to_pydantic_ai_tools(spec, tool_runner, sink=sink)
    kwargs: dict[str, Any] = {
        "system_prompt": system,
        "tools": tools,
    }
    if output_type is not None:
        kwargs["output_type"] = output_type
    if spec.temperature is not None:
        kwargs.setdefault("model_settings", {"temperature": spec.temperature})
    kwargs.update(agent_kwargs)
    return Agent(model, **kwargs)
