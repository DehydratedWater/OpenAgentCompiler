# LangChain Runtime Agents

The compiled dialects (opencode / claude / pi / codex) produce *files*
that an external CLI runs. **Runtime agents** are the other execution
shape: the same `AgentDefinition` running *inside your Python process*,
as a streaming, tool-calling chat agent built on LangChain. This page
describes how that runtime layer is put together — the pieces, their
contracts, and where your code takes over. For the step-by-step how-to,
see [the interactive tier guide](interactive-tier.md); for when to pick
which tier, see [execution tiers](../concepts/execution-tiers.md).

## Architecture

```
AgentDefinition ──build_interactive_spec()──▶ InteractiveAgentSpec
                                                    │
                              (runtime-agnostic intermediate)
                                                    │
                 ┌──────────────────────────────────┴───────────────┐
                 ▼                                                  ▼
      LangChain binding                              framework-owned loop
  bind() → prompt | ChatOpenAI(+tools)            run_interactive() → RunResult
                 │
                 ▼
   your orchestration: LangGraph,
   AgentExecutor, or a manual loop
```

The design splits responsibility in three layers:

1. **The spec** (`open_agent_compiler.interactive.spec`) — a frozen,
   runtime-agnostic Pydantic model. No LangChain imports.
2. **The binding** (`open_agent_compiler.interactive.bindings.langchain_binding`)
   — turns the spec into LangChain pieces. Imports `langchain-openai`
   lazily; kept deliberately thin.
3. **The orchestration loop** — *yours*. The framework hands you a
   streaming LCEL runnable with tools bound; whether that sits inside a
   LangGraph graph, an `AgentExecutor`, or a hand-rolled while-loop is an
   application decision the framework does not make for you.

## Layer 1: `InteractiveAgentSpec`

`build_interactive_spec(agent=..., live_profile=...)` derives the spec
from a registered `AgentDefinition` plus a **live** provider profile — a
`SplitProfile` whose `ModelPreset.provider_options` carry the
`base_url` / `api_key_env` of your interactive provider (typically *not*
the provider the workers compile against):

```python
from open_agent_compiler import build_interactive_spec

spec = build_interactive_spec(agent=my_agent, live_profile=LIVE_PROFILE)
```

The spec is a frozen snapshot of everything a binding needs:

| Field | Contents |
|-------|----------|
| `agent_id` | from `AgentDefinition.header.agent_id` |
| `model` | the resolved `ModelPreset` (model id, sampling, provider options) |
| `system_prompt` | rendered by `render_interactive_prompt` — the agent's intent (system prompt, workflow as *guidance*, skills as *capabilities*) **without** worker scaffolding: no bash-invocation docs, no `TODO.md` bookkeeping, no SECURITY POLICY block, because interactive tools bind natively and the process boundary is yours |
| `tools` | a tuple of `ToolSpec`s — every tool reachable from the agent (`extra_tools` plus workflow-step tools), de-duplicated by name |
| `output_schema` | optional JSON schema for structured replies |

`ToolSpec` is intentionally small: `name`, `description`, a best-effort
JSON `input_schema`, and `script_paths` pointing at the backing
`ScriptTool` files so a runner can locate what to execute.

## Layer 2: the LangChain binding

Three functions, composable or used together via `bind`:

### `build_chat_model(spec, *, api_key=None, streaming=True, **overrides)`

Constructs a streaming `ChatOpenAI` pointed at the spec's live provider:
`model_id`, `base_url`, and `temperature` come from the preset. API key
resolution is forgiving by design — explicit argument, then the
`api_key_env` environment variable, then a `"not-needed"` placeholder,
because many local OpenAI-compatible servers (vLLM, llama.cpp, LM
Studio) ignore the key and should not fail client construction.

### `to_langchain_tools(spec, runner=None, *, sink=None)`

Converts each `ToolSpec` into a `langchain_core.tools.Tool`. The tools
do **not** execute anything themselves — each one routes its call to
your `ToolRunner`:

```python
ToolRunner = Callable[..., str]   # (tool_name, args_dict) -> result text
```

Wiring execution is the consumer's job: a subprocess invoking the
`ScriptTool`, an HTTP call, an in-process function — none of the
framework's business. A runner may optionally widen its signature to
`(name, args, emitter)` to emit mid-run progress (detected via
introspection by `runner_accepts_emitter`). If a tool is called with no
runner configured, that is a hard `RuntimeError` — silent no-op tools
would corrupt the conversation.

### `bind(spec, *, tool_runner=None, api_key=None, streaming=True, sink=None)`

Assembles the standard LCEL runnable:

```
ChatPromptTemplate(SystemMessage(spec.system_prompt), MessagesPlaceholder("messages"))
  | ChatOpenAI(...).bind_tools(tools)
```

Invoke or stream it with `{"messages": [...]}`. One deliberate detail:
the system prompt goes in as a **literal `SystemMessage`**, not a
`("system", str)` template entry — agent prompts routinely contain JSON
examples with `{ }`, which the f-string template parser would misread as
template variables and reject.

`bind` returns one model call's worth of pipeline. It does not loop.

## Layer 3: the orchestration loop (yours)

A tool-calling *agent* needs a loop: call the model, execute any tool
calls, append results, call again. The binding deliberately stops short
of owning that loop — drop the runnable (or `build_chat_model` +
`to_langchain_tools` separately) into whatever orchestrator your app
uses:

```python
from langgraph.prebuilt import create_react_agent

model = build_chat_model(spec)
tools = to_langchain_tools(spec, runner=my_tool_runner)
graph = create_react_agent(model, tools, prompt=spec.system_prompt)
result = graph.invoke({"messages": [("user", "summarize today's alerts")]})
```

If you don't want to own a loop, the framework ships one:
`run_interactive(spec, prompt, tool_runner=...)` runs a full turn
in-process (model call → tool rounds → history threading) and returns a
`RunResult` with `ToolCallRecord`s, making interactive runs scoreable by
the same evaluators and [improvement loop](improvement-loop.md) as
workers. Note that `run_interactive` talks to the provider through its
own OpenAI-compatible client, not through LangChain — the LangChain
binding exists for apps that live in the LangChain ecosystem; the
framework loop exists for apps that don't.

## Event stream

Pass a `sink` to `bind` / `to_langchain_tools` and every tool call
brackets itself with events — `tool.start`, `tool.end`, `tool.error` —
and hands the runner an `EventEmitter` for mid-run `progress` /
`message` events. `emitter.child("source")` namespaces events from a
dispatched subagent onto the same stream.

Sinks are tiny and swappable:

| Sink | Use |
|------|-----|
| `CallbackSink(fn)` | call a function per event (any callable is auto-wrapped via `as_sink`) |
| `QueueSink(queue)` | push onto an `asyncio.Queue` — drain from your SSE/websocket handler |
| `CollectingSink()` | accumulate into a list — assertions in tests |
| `NullSink()` | discard (the no-sink default has zero overhead — event code only runs when a sink is present) |

## Dependencies and failure modes

- The binding needs the `langchain` extra
  (`pip install "open-agent-compiler[langchain]"` →
  `langchain-core` + `langchain-openai`). The core package never imports
  LangChain; imports happen lazily inside the binding functions and a
  missing dependency raises `MissingDependencyError` with the install
  hint.
- Thinking-style local models (Qwen3.x on vLLM) return empty content
  unless thinking is disabled per call — set `extra_body` on the preset;
  see [the interactive tier guide](interactive-tier.md#8-thinking-off-for-local-models).
- Long, side-effecting jobs don't belong in the runtime agent — give it
  the bundled `SpawnAgentTool` and dispatch to a compiled worker; see
  [the interactive tier guide](interactive-tier.md#9-dispatch-heavy-work-to-compiled-workers).

## Relationship to the compiled dialects

Both shapes derive from the **same** `AgentDefinition` — that is the
framework's unified interface. What changes is the delivery:

| | Compiled worker | LangChain runtime agent |
|---|---|---|
| Artifact | `.opencode/` / `.claude/` / `.pi/` / `.codex/` file tree | in-process objects, no files |
| Prompt rendering | full scaffolding (workflow steps, TODO bookkeeping, SECURITY POLICY, bash tool docs) | intent only (`render_interactive_prompt`) |
| Tools | bash / JSON contracts executed by the CLI runtime | native tool-calling routed to your `ToolRunner` |
| Model/provider | worker profile | live profile (often a local OpenAI-compatible server) |
| Lifecycle | fire-and-forget, side-effects | streaming request/response |

## Alternative binding: PydanticAI

The same spec binds to PydanticAI
(`bindings/pydantic_ai_binding.py`, extra:
`open-agent-compiler[pydantic-ai]`): `bind(spec, tool_runner=...)`
returns a ready `pydantic_ai.Agent` with the spec's tools routed
through the identical `ToolRunner`/event contract, and `output_type=`
uses PydanticAI's native structured output instead of the JSON-
instruction fallback. Both bindings are ~one-file adapters — that
swappability is the point of the spec layer.

## Optimizing the runtime agent

The realtime tier is an autoloop target of its own:
`build_interactive_evaluator` scores loop candidates by running them
through `run_interactive`, so the interactive rendering gets tuned on
what it actually sends — see
[optimization targets](optimization-targets.md).

## See Also

- [The Interactive Tier](interactive-tier.md) — step-by-step how-to
- [Execution Tiers](../concepts/execution-tiers.md) — when to use which tier
- `open_agent_compiler/interactive/bindings/langchain_binding.py` — the binding source
- `examples/35_fastapi_dispatch/` — interactive front + worker dispatch over HTTP
- `examples/85_matrix_live_chat/` — a realtime agent dispatching compiled workers across harnesses
