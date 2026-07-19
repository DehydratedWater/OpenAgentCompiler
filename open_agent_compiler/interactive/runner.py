"""In-process interactive agent runner — the framework-owned tool loop.

The LangChain binding deliberately stops at "here are the pieces, assemble
your own agent loop". That leaves every consumer re-writing the same
tool-calling orchestration — and, worse, leaves the loop *outside* the
framework's test/improve machinery. This module closes that gap: it runs an
`InteractiveAgentSpec` end-to-end in-process (system prompt + history + user
turn → model → tool calls → tool results → … → final answer), recording every
tool invocation as a `ToolCallRecord` so the autoloop's probes and evaluators
can score a real interactive run exactly like a worker run.

Design constraints carried over from the rest of the interactive target:

* **Dependency-light.** Only pydantic + stdlib at import time. The official
  ``openai`` client is imported lazily inside `OpenAICompatClient` (the same
  `_require` pattern as the LangChain binding) and is only needed when no
  custom `ChatClient` is injected — tests run on a scripted fake with zero
  network and zero optional deps.
* **No raw provider endpoints.** The provider guard forbids endpoint string
  literals like chat-completions paths anywhere in code; the ``openai``
  client builds its own request paths and is pointed at the LOCAL
  OpenAI-compatible server (e.g. vLLM qwen) via the spec's ``base_url``.
  The strong teacher is still only ever reached through opencode.
* **Same primitives.** Tool execution goes through the same `ToolRunner`
  callable shape as the LangChain binding (``(name, args)`` or
  ``(name, args, emitter)``) and the same event sink/emitter machinery, so a
  runner/sink written for one binding drops into the other unchanged.

Local-model quirk worth knowing: Qwen3.x served by vLLM returns EMPTY content
unless thinking is disabled via ``extra_body={"chat_template_kwargs":
{"enable_thinking": false}}``. The consumer sets that in
``ModelPreset.provider_options["extra_body"]`` (as a JSON string, since
provider_options values are strings); `OpenAICompatClient.from_spec` parses
and forwards it verbatim.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.interactive.events import EventEmitter, EventSink, invoke_runner
from open_agent_compiler.interactive.spec import InteractiveAgentSpec
from open_agent_compiler.testing.evaluation import ToolCallRecord

# (tool_name, args_dict) -> result text; optionally widened to
# (tool_name, args_dict, emitter). Same contract as the LangChain binding's
# ToolRunner — execution is the consumer's business, routing is ours.
ToolRunner = Callable[..., str]


class MissingDependencyError(RuntimeError):
    pass


def _require(modname: str):
    try:
        return __import__(modname, fromlist=["_"])
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise MissingDependencyError(
            f"the in-process runner needs '{modname}'. Install it: "
            f"pip install {modname}"
        ) from exc


# --- chat client --------------------------------------------------------

class ChatToolCall(BaseModel):
    """One tool call the model asked for, provider-shape already normalised
    (arguments JSON-decoded into a plain dict)."""

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """One assistant turn: text content and/or requested tool calls."""

    model_config = ConfigDict(frozen=True)

    content: str = ""
    tool_calls: list[ChatToolCall] = Field(default_factory=list)


class ChatClient(Protocol):
    """Pluggable completion backend. Tests script a fake; production uses
    `OpenAICompatClient` against the spec's live (local) provider."""

    def complete(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
        model: str,
        **params: Any,
    ) -> ChatResponse: ...


def _resolve_api_key(spec: InteractiveAgentSpec, api_key: str | None) -> str:
    if api_key:
        return api_key
    env = spec.api_key_env
    if env and os.environ.get(env):
        return os.environ[env]
    # Local OpenAI-compatible servers usually ignore the key; send a
    # placeholder rather than letting the client raise on construction.
    return "not-needed"


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    """Decode a tool call's arguments leniently — never raise on model junk."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": parsed}


class OpenAICompatClient:
    """ChatClient over the official ``openai`` client (lazy import), pointed
    at an OpenAI-compatible server (local vLLM) via ``base_url``.

    ``default_params`` (temperature, extra_body, …) are merged under any
    per-call params; ``from_spec`` assembles them from the preset.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str = "not-needed",
        default_params: dict[str, Any] | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self.default_params = dict(default_params or {})
        self._client: Any = None  # built lazily so importing this module is free

    @classmethod
    def from_spec(
        cls, spec: InteractiveAgentSpec, *, api_key: str | None = None
    ) -> "OpenAICompatClient":
        params: dict[str, Any] = {}
        if spec.temperature is not None:
            params["temperature"] = spec.temperature
        extra = spec.model.provider_options.get("extra_body")
        if extra:
            # provider_options values are strings, so extra_body arrives as a
            # JSON string (e.g. the qwen enable_thinking=false switch). Accept
            # a dict too for hand-built presets.
            params["extra_body"] = (
                json.loads(extra) if isinstance(extra, str) else extra
            )
        return cls(
            base_url=spec.base_url,
            api_key=_resolve_api_key(spec, api_key),
            default_params=params,
        )

    def _ensure_client(self) -> Any:
        if self._client is None:
            openai = _require("openai")
            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = openai.OpenAI(**kwargs)
        return self._client

    def complete(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str,
        **params: Any,
    ) -> ChatResponse:
        client = self._ensure_client()
        kwargs = {**self.default_params, **params}
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        if tools:
            kwargs["tools"] = tools
        response = client.chat.completions.create(
            model=model, messages=messages, **kwargs
        )
        message = response.choices[0].message
        calls = [
            ChatToolCall(
                id=tc.id or "",
                name=tc.function.name,
                args=_parse_tool_args(tc.function.arguments),
            )
            for tc in (message.tool_calls or [])
        ]
        return ChatResponse(content=message.content or "", tool_calls=calls)


# --- run ----------------------------------------------------------------

class RunResult(BaseModel):
    """Everything one interactive run produced — transcript, tool records,
    optional structured payload — in the shape the autoloop evaluates."""

    output_text: str
    messages: list[dict]
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    structured: Any = None
    rounds: int
    error: str | None = None


def _tool_dicts(spec: InteractiveAgentSpec) -> list[dict] | None:
    """Spec tools → OpenAI-style function-tool dicts (permissive schema when
    the spec carries none, so the model can still call the tool)."""
    tools = []
    for tool in spec.tools:
        parameters = tool.input_schema or {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": parameters,
            },
        })
    return tools or None


def _structured_instruction(schema: dict[str, Any]) -> str:
    return (
        "Answer with a single JSON object matching this JSON schema "
        "(no prose outside the JSON):\n" + json.dumps(schema)
    )


_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_-]+)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """First JSON object in `text`, leniently: prefer a code-fenced block,
    then scan for the first `{`; trailing prose after the object is fine."""
    candidate = text
    fenced = _FENCE_RE.search(text)
    if fenced:
        candidate = fenced.group(1)
    start = candidate.find("{")
    if start == -1:
        raise ValueError("no JSON object found in output")
    try:
        obj, _ = json.JSONDecoder().raw_decode(candidate[start:])
    except ValueError as exc:
        raise ValueError(f"invalid JSON object: {exc}") from exc
    return obj


def _assistant_tool_calls_message(calls: list[ChatToolCall]) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.args),
                },
            }
            for call in calls
        ],
    }


def run_interactive(
    spec: InteractiveAgentSpec,
    user_input: str | list[dict],
    *,
    tool_runner: ToolRunner | None = None,
    client: ChatClient | None = None,
    sink: EventSink | Callable[..., Any] | None = None,
    max_tool_rounds: int = 8,
    history: list[dict] | None = None,
    **params: Any,
) -> RunResult:
    """Run one interactive turn end-to-end, in-process.

    `user_input` is a plain user string or a ready-made list of message dicts
    for the turn; either way the spec's system prompt (plus the structured-
    output instruction when `spec.output_schema` is set) and `history` come
    first. Tool calls route through `tool_runner` (same callable shape as the
    LangChain binding), bracketed with tool.start/tool.end/tool.error events
    on `sink` (source = the agent id). A tool failure is RECORDED, not raised:
    the error text goes back to the model as the tool result so it can
    recover, and lands on the `ToolCallRecord` for the evaluators.

    `max_tool_rounds` caps how many tool-execution rounds run; if the model
    still asks for tools after the cap, the run ends with
    ``error="max tool rounds reached"``.
    """
    if client is None:
        client = OpenAICompatClient.from_spec(spec)

    # The structured-output instruction is MERGED into the one leading system
    # message (not appended as a second one): strict chat templates — qwen on
    # vLLM included — 400 on any system message that isn't first.
    system = spec.system_prompt
    if spec.output_schema is not None:
        system = f"{system}\n\n{_structured_instruction(spec.output_schema)}"
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(history or [])
    if isinstance(user_input, str):
        messages.append({"role": "user", "content": user_input})
    else:
        messages.extend(user_input)

    tools = _tool_dicts(spec)
    emitter = EventEmitter(sink, source=spec.agent_id)
    records: list[ToolCallRecord] = []
    rounds = 0
    tool_rounds = 0
    content = ""
    error: str | None = None

    while True:
        response = client.complete(
            messages=messages, tools=tools, model=spec.model_id, **params
        )
        rounds += 1
        content = response.content
        if content:
            # Per-turn visibility on the event stream (async servers /
            # UIs draining a sink see turns as they land).
            emitter.message(content)
        if not response.tool_calls:
            break
        if tool_runner is None:
            error = "model requested tools but no tool_runner provided"
            break
        if tool_rounds >= max_tool_rounds:
            # The model is STILL asking for tools after the cap — that, not
            # merely hitting the cap, is the failure worth recording.
            error = "max tool rounds reached"
            break
        tool_rounds += 1
        messages.append(_assistant_tool_calls_message(response.tool_calls))
        for call in response.tool_calls:
            emitter.tool_start(tool=call.name, args=call.args)
            try:
                output = invoke_runner(tool_runner, call.name, call.args, emitter)
            except Exception as exc:  # recorded + fed back, never raised
                reason = str(exc) or type(exc).__name__
                records.append(
                    ToolCallRecord(name=call.name, args=call.args, error=reason)
                )
                emitter.tool_error(reason, tool=call.name)
                result_text = f"ERROR: {reason}"
            else:
                records.append(
                    ToolCallRecord(name=call.name, args=call.args, output=output)
                )
                emitter.tool_end(tool=call.name, result=str(output))
                result_text = str(output)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result_text}
            )

    messages.append({"role": "assistant", "content": content})

    structured: Any = None
    if spec.output_schema is not None and error is None:
        try:
            structured = _extract_json(content)
        except ValueError as exc:
            error = f"structured output parse failed: {exc}"

    return RunResult(
        output_text=content,
        messages=messages,
        tool_calls=records,
        structured=structured,
        rounds=rounds,
        error=error,
    )


async def run_interactive_async(
    spec: InteractiveAgentSpec,
    user_input: str | list[dict],
    *,
    tool_runner: ToolRunner | None = None,
    client: ChatClient | None = None,
    sink: EventSink | Callable[..., Any] | None = None,
    max_tool_rounds: int = 8,
    history: list[dict] | None = None,
    **params: Any,
) -> RunResult:
    """Async entry point for `run_interactive`.

    The blocking turn (provider round-trips + tool subprocesses) runs in
    a worker thread via asyncio.to_thread, so an async server (FastAPI,
    a telegram bot's event loop) can serve turns concurrently without
    blocking. Incremental visibility comes from `sink`: tool.start/end/
    error and per-turn `message` events fire from inside the run —
    token-level streaming remains the bindings' job (LangChain /
    PydanticAI), which stream natively against the same spec.
    """
    import asyncio

    return await asyncio.to_thread(
        run_interactive, spec, user_input,
        tool_runner=tool_runner, client=client, sink=sink,
        max_tool_rounds=max_tool_rounds, history=history, **params,
    )


__all__ = [
    "ChatToolCall",
    "ChatResponse",
    "ChatClient",
    "run_interactive_async",
    "OpenAICompatClient",
    "RunResult",
    "ToolRunner",
    "MissingDependencyError",
    "run_interactive",
]
