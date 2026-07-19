# The interactive tier

In this guide you'll take an agent you already register for compiled
workers and run it as an in-process, streaming chat agent: build an
`InteractiveAgentSpec`, bind it to a LangChain runnable (or the
framework's own tool loop), stream events, get structured output, and
dispatch heavy work back to compiled workers. For *why* the two tiers
exist and when to use which, read
[execution tiers](../concepts/execution-tiers.md) first — this page is
the how.

## 1. Install the extra

The core package stays dependency-light; the LangChain binding is an
extra, imported lazily:

```bash
pip install "open-agent-compiler[langchain]"
```

## 2. Point a live profile at your interactive provider

Workers and the live tier usually use different providers (e.g. workers
through opencode, live tier on a local OpenAI-compatible vLLM). The
live provider is just another `SplitProfile` — a `ModelPreset` whose
`provider_options` carry the `base_url` / `api_key_env` the binding
needs:

```python
from open_agent_compiler import ModelPreset, SamplingDefaults, SplitProfile

LOCAL = ModelPreset(
    name="local-default", provider="local-vllm", model_id="my-local-model",
    sampling=SamplingDefaults(temperature=0.7),
    provider_options={
        "base_url": "http://localhost:8000/v1",
        "api_key_env": "LOCAL_API_KEY",   # optional; placeholder sent if unset
    },
)
LIVE_PROFILE = SplitProfile(name="live", preset=LOCAL,
                            class_map={"default": LOCAL})
```

## 3. Build the spec from a registered agent

```python
from open_agent_compiler import build_interactive_spec

spec = build_interactive_spec(agent=my_agent_definition, live_profile=LIVE_PROFILE)
```

`build_interactive_spec` renders the agent's core intent — system
prompt, workflow as guidance, skills as capabilities — *without* the
worker scaffolding (bash/todo/security blocks), because interactive
tools bind natively. It collects every tool reachable from the agent
(`extra_tools` plus workflow-step tools) into runtime-agnostic
`ToolSpec`s.

## 4. Bind to LangChain and stream

```python
from open_agent_compiler.interactive.bindings.langchain_binding import bind

def my_tool_runner(name: str, args: dict) -> str:
    ...  # route to your ScriptTool subprocess, an API call, etc.

runnable = bind(spec, tool_runner=my_tool_runner)   # streaming LCEL runnable

for chunk in runnable.stream({"messages": [("user", "make it punchier")]}):
    print(chunk, end="", flush=True)
```

`bind` returns `prompt | chat_model` with the spec's tools attached via
`bind_tools`; for a full tool-calling loop drop the pieces into your
own LangGraph/AgentExecutor, or use the framework-owned loop below.

## 5. Stream tool events to your UI

Pass a `sink` and every tool call brackets itself with
`tool.start` / `tool.end` / `tool.error` events; a runner that widens
its signature to `(name, args, emitter)` can push mid-run progress on
the same stream, and `emitter.child("subagent-x")` attributes a
dispatched subagent's events separately:

```python
import asyncio
from open_agent_compiler import QueueSink   # also: CallbackSink, CollectingSink

sink = QueueSink(asyncio.Queue())           # drain in your SSE/websocket loop
runnable = bind(spec, tool_runner=my_tool_runner, sink=sink)
```

## 6. Or use the framework-owned loop (records tool calls)

`run_interactive` runs one full turn in-process — model call, tool
execution rounds, history threading — and returns a `RunResult` whose
`tool_calls` are `ToolCallRecord`s, so interactive runs are scoreable by
the same evaluators and [improvement loop](improvement-loop.md) as
workers:

```python
from open_agent_compiler.interactive import run_interactive

result = run_interactive(spec, "summarize today's alerts",
                         tool_runner=my_tool_runner, max_tool_rounds=8)
print(result.output_text, result.tool_calls)
```

Tool failures are recorded and fed back to the model as the tool
result — never raised — so the agent can recover.

## 7. Structured output

Pass a JSON schema when building the spec and `run_interactive` merges
a format instruction into the system message and parses the reply:

```python
spec = build_interactive_spec(agent=my_agent, live_profile=LIVE_PROFILE,
                              output_schema={"type": "object",
                                             "properties": {"intent": {"type": "string"}}})
result = run_interactive(spec, "route this message")
print(result.structured)        # parsed dict, or result.error on parse failure
```

## 8. Thinking-off for local models

Qwen3.x-style thinking models on vLLM return empty `content` unless
thinking is disabled per call. Set it on the preset —
`provider_options` values are strings, so `extra_body` is a JSON
string that `OpenAICompatClient.from_spec` decodes:

```python
LOCAL = ModelPreset(
    name="local-default", provider="local-vllm", model_id="my-local-model",
    provider_options={
        "base_url": "http://localhost:8000/v1",
        "extra_body": '{"chat_template_kwargs": {"enable_thinking": false}}',
    },
)
```

Structured output plus thinking-off is the reliable combination for a
snappy local first-contact tier.

## 9. Dispatch heavy work to compiled workers

The interactive agent should stay fast; long, side-effecting jobs
belong to compiled workers. Give the interactive agent the bundled
`SpawnAgentTool` (a typed `ScriptTool`) and it returns a `TaskHandle`
the chat can track:

```python
from open_agent_compiler import SpawnAgentInput, SpawnAgentTool

out = SpawnAgentTool().execute(SpawnAgentInput(
    agent_name="report-builder-primary",   # a compiled agent in the build tree
    prompt="Build the weekly report.",
    spawn_async=True,                      # return immediately with a handle
))
print(out.task.run_id, out.task.status)
```

See `examples/31_spawn_agent` for the parent-spawns-worker composition
and `examples/35_fastapi_dispatch` for awaiting handles over HTTP. The
worker side is covered by the [opencode dialect](../dialects/opencode.md).
