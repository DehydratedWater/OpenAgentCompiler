# Execution tiers: one definition, two lanes

This page explains the framework's fast/slow split: how the *same*
`AgentDefinition` runs both as a long-lived autonomous **worker** (compiled to
an agent runtime) and as a snappy in-process **interactive** agent (bound to a
streaming chat model) — and when to route to which.

```
                      AgentDefinition (one source of truth)
                                     │
              ┌──────── worker tier ─┴─── interactive tier ────────┐
              ▼                                                    ▼
   CompileScript(dialect=...)                        build_interactive_spec(...)
              │                                                    │
   .opencode/ .claude/ .pi/ trees                       InteractiveAgentSpec
   run as a SUBPROCESS by a                       bound IN-PROCESS: LangChain
   coding-agent runtime                           runnable or run_interactive()
              │                                                    │
   long-running · side-effecting                  streaming · request/response
   fire-and-forget · strong isolation             sub-second first token
```

## The worker tier (slow lane)

Compile the registry to a dialect and you get markdown agent trees a runtime
executes as a subprocess:

```python
from pathlib import Path
from open_agent_compiler.compiler.script import CompileScript
from agents import registry

CompileScript(target=Path("build"), factory=registry,
              config="prod", dialect="opencode", clean=True).run()
```

```bash
cd build && opencode run --agent primary "Research topic X and write report.md"
```

The worker contract is **fire-and-forget**: you hand a task over, the agent
runs autonomously for seconds to minutes, and it communicates by side-effects
— files written, scripts executed, subagents dispatched. This is where all
the compiled scaffolding lives: MANDATORY WORKFLOW steps with criteria and
routes, strict todo bookkeeping, `permission:` enforcement plus the SECURITY
POLICY block, bash-invoked ScriptTools under `scripts/`, and subagent
dispatch. Isolation is strong because the runtime is a separate process with
its own permission wall.

Use it for: heavy tool work, multi-step jobs with review loops, anything you
want testable and resumable rather than fast.

## The interactive tier (fast lane)

The same definition derives an `InteractiveAgentSpec` — an in-process,
runtime-agnostic intermediate — via `build_interactive_spec`:

```python
from open_agent_compiler import (
    ModelPreset, SamplingDefaults, VariantSpec, build_interactive_spec,
)

LIVE = VariantSpec(name="live", preset=ModelPreset(
    name="local-chat", provider="openai",
    model_id="my-local-model",
    sampling=SamplingDefaults(temperature=0.3),
    provider_options={"base_url": "http://localhost:8000/v1",
                      "api_key_env": "LOCAL_API_KEY"},
))

spec = build_interactive_spec(agent=my_definition, live_profile=LIVE)
```

Three deliberate differences from the worker compile:

- **The prompt is leaner.** `render_interactive_prompt` emits only the
  agent's core intent — system prompt, workflow as plain guidance, skills as
  capabilities. No bash syntax, no todo bootstrap, no security block: tools
  bind *natively* here, so worker scaffolding would be noise.
- **The provider is resolved separately.** `live_profile` is a
  `VariantSpec`/`SplitProfile` pointing at your *interactive* provider (often
  a local OpenAI-compatible server), independent of what the workers compile
  to. One registry, two provider maps.
- **Nothing touches disk.** The spec is a frozen Pydantic model holding
  `agent_id`, resolved `ModelPreset`, `system_prompt`, `tools`
  (as `ToolSpec`s), and an optional `output_schema` for structured output.

Run it with the framework-owned loop — model → tool calls → tool results →
… → answer, entirely in-process:

```python
from open_agent_compiler.interactive.runner import run_interactive

def tool_runner(name: str, args: dict) -> str:
    ...  # route to your ScriptTool, an API, a subprocess — your call
    return "done"

result = run_interactive(spec, "Summarize today's inbox", tool_runner=tool_runner)
print(result.output_text)      # final answer
print(result.tool_calls)       # ToolCallRecord list — scoreable by the autoloop
```

Or bind it to LangChain for a streaming LCEL runnable (install the
`langchain` extra):

```python
from open_agent_compiler.interactive.bindings.langchain_binding import bind

runnable = bind(spec, tool_runner=tool_runner)   # prompt | chat model (+tools)
for chunk in runnable.stream({"messages": [("user", "make it punchier")]}):
    ...
```

`run_interactive` gives you the complete loop (multi-round tool calling,
`max_tool_rounds` cap, structured-output extraction when `output_schema` is
set, tool errors recorded and fed back rather than raised). The LangChain
binding stays thin on purpose — pieces for your own LangGraph/agent loop.
Both share the same `ToolRunner` callable shape and the same event
sink/emitter machinery (`tool.start` / `tool.end` / `tool.error`), so a
runner written for one drops into the other. Every run yields
`ToolCallRecord`s, which means interactive runs are evaluable by the same
[improvement loop](../guides/improvement-loop.md) as workers.

## Choosing a lane

| Signal | Route to |
|---|---|
| User is waiting on the reply | interactive |
| Structured output for program consumption | interactive (`output_schema`) |
| Minutes of autonomous multi-step work | worker |
| Heavy side-effects, needs permission walls | worker |
| Must survive beyond the request | worker |
| Streaming tokens into a chat UI | interactive |

The rule of thumb: **interactive returns a value; a worker returns a
handle.** If the caller needs the answer now, go in-process. If the caller
needs the *job done eventually*, compile a worker.

## Composing the two

A typical application uses both, from one registry: the interactive agent
holds the conversation, and one of its tools dispatches a compiled worker.

```python
def tool_runner(name: str, args: dict) -> str:
    if name == "research_task":
        # fire-and-forget: launch the compiled worker, return a handle
        import subprocess
        subprocess.Popen(
            ["opencode", "run", "--print-logs",
             "--agent", "researcher-primary", args["input"]],
            cwd="build",
        )
        return "started: research job dispatched, results land in report.md"
    ...
```

The user gets a sub-second conversational acknowledgment; the heavy job runs
to completion in its own process and reports by side-effect. (The framework
also ships a typed `SpawnAgentTool` for exactly this dispatch-and-return-a-
`TaskHandle` pattern.) Note the `-primary` twin: subagents aren't directly
invocable, so slots meant for external dispatch set
`also_compile_as_primary=True` — see
[Registry and compilation](registry-and-compilation.md).

Because both lanes come from the same `AgentDefinition`, improving the
definition improves both: promote a better prompt section and the next worker
compile *and* the next `build_interactive_spec` call pick it up.

To go deeper: [Interactive tier guide](../guides/interactive-tier.md) for
events, sinks, and structured output;
[LangChain runtime agents](../guides/langchain-runtime.md) for the
architecture of the in-process runtime layer;
[Variants and profiles](../guides/variants-and-profiles.md)
for split live/worker providers; or start from
[your first agent](../getting-started/first-agent.md).
