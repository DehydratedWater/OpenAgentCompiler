"""interactive-agents skill — the two-target / dual-provider model."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Two ways to use an agent: workers and interactive

A framework `AgentDefinition` can be used **two distinct ways**, from one set
of primitives (definitions, tools, skills, presets, variants, tests):

| | **Worker** (compiled dialect) | **Interactive** (binding) |
|---|---|---|
| Emits | `.opencode/` / `.claude/` / `.pi/` files | an in-process runnable |
| Tools bind to | bash / JSON emission | native tool-calling |
| Contract | fire-and-forget, side-effects, a handle | streaming, request/response, a value |
| Use it for | long, testable, autonomous tasks | the dynamic / chat layer |

The worker is the framework's home turf — long-running, side-effecting agents
run by a coding-agent runtime, where the permission model, subagents, MCP,
workflow/gates, todo tracking, and the improvement loop earn their keep.
Workers compile through `CompileScript(dialect=...)` to one of the registered
dialects — `opencode` (default), `claude`, or `pi` (list them with
`oac info --dialects`). The interactive target is for the
conversation/streaming layer; it does **not** make the framework a runtime —
it *compiles to* one (LangChain first) and stops.

A typical app uses both: the **interactive** agent holds the chat and
**dispatches** a **worker** that runs in the background to completion and
communicates by side-effects (writes to a DB, sends a message). The handle
(`SpawnAgentTool` → `TaskHandle`) is how the chat tracks it.

## Building an interactive agent

```python
from open_agent_compiler import build_interactive_spec, SplitProfile, ModelPreset
from open_agent_compiler.interactive.bindings.langchain_binding import bind

spec = build_interactive_spec(agent=my_agent, live_profile=LIVE_PROFILE)
runnable = bind(spec, tool_runner=my_tool_runner)   # streaming LCEL runnable
for chunk in runnable.stream({"messages": [("user", "make it punchier")]}):
    ...
```

`build_interactive_spec` renders the agent's CORE intent (system prompt +
workflow as guidance + skills as capabilities) **without** opencode's
bash/todo/security scaffolding, because interactive tools bind natively.

## Dual providers — workers and live use different models

z.ai's coding plan works with opencode (workers) but not with LangChain. So
the worker compile and the interactive binding resolve the *same* agent's
`model_class` through **different profiles**:

```python
WORKER_PROFILE = SplitProfile(name="worker", preset=ZAI_DEFAULT,
    class_map={"default": ZAI_DEFAULT, "fast": ZAI_FAST})          # opencode
LIVE_PROFILE = SplitProfile(name="live", preset=LOCAL_DEFAULT,
    class_map={"default": LOCAL_DEFAULT, "fast": LOCAL_FAST})      # interactive
```

No new abstraction — the live provider is just another `SplitProfile`, and a
preset's `provider_options` carries the `base_url` / `api_key_env` the binding
needs. Tools and prompts optimised once in the worker world bind straight into
the interactive agent.

## Emitting events (optional) — tools, subagents, workflow progress

A chat UI wants to *show what the agent is doing*: "calling priority-manager…",
a subagent's progress, "step 3/7" of a deterministic workflow. The framework
ships an optional sink/emitter for this. It is dependency-light (no LangChain
import) so a plain deterministic workflow can emit too.

Pass a `sink` to `bind`/`to_langchain_tools` and every tool brackets itself
with `tool.start` / `tool.end` / `tool.error` events:

```python
from open_agent_compiler import CollectingSink   # or CallbackSink, QueueSink
sink = QueueSink(asyncio.Queue())          # drain it in your SSE/websocket loop
runnable = bind(spec, tool_runner=run, sink=sink)
```

A runner that widens its signature to `(name, args, emitter)` can push
mid-run progress on the SAME stream — this is how a **subagent dispatched as a
tool** reports back, and `emitter.child("subagent-x")` gives the subagent its
own attributable source while sharing the sink:

```python
def run(name, args, emitter):              # 3-arg form is auto-detected
    emitter.progress("searching", current=1, total=3)
    sub = emitter.child("subagent-research")
    sub.progress("reading docs")
    return do_work(args)
```

With no `sink` the tools behave exactly as before — zero overhead. For a
**deterministic (non-LLM) workflow**, use the emitter directly, no binding:

```python
from open_agent_compiler import EventEmitter
em = EventEmitter(sink, source="build-pipeline")
for i, step in enumerate(steps, 1):
    em.progress(f"{step.name}", current=i, total=len(steps))
    step.run()
```

Sinks: `NullSink` (default no-op), `CallbackSink(fn)`, `CollectingSink` (a
list, for tests), `QueueSink(q)` (`put_nowait` — the streaming path). A bare
callable is coerced to a `CallbackSink` automatically.

## Running a pure-prompt ("function") agent yourself

If an agent is pure-prompt and you just want `prompt → value`, you don't need
a runtime at all. Read the compiled artifact and make one call:

```python
from open_agent_compiler import load_compiled_agent
a = load_compiled_agent(".opencode/agents/critic-primary.md")
# a.model, a.system_prompt — feed them to LangChain / the raw SDK / your call
```

The framework owns the artifact format (so it reads it back), but execution of
function agents is the ecosystem's job — don't rebuild LangChain inside the
compiler.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="interactive-agents",
        description=(
            "The two-target model: opencode workers (long-running, side-effecting,"
            " testable) vs interactive bindings (streaming chat), from shared"
            " primitives — with dual provider profiles (worker vs live) and the"
            " compiled-artifact reader for pure-prompt function agents."
        ),
        body_markdown=BODY,
        tools_hint=(
            "build_interactive_spec", "SplitProfile",
            "open_agent_compiler.interactive.bindings.langchain_binding.bind", "load_compiled_agent",
        ),
    )
