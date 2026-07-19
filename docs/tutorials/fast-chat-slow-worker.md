# Tutorial: fast chat, slow worker

*Mini-project for: the execution-tier split — an in-process interactive
agent that hands heavy jobs to a compiled opencode worker.*

## The problem

A compiled opencode worker is great at long, tool-heavy jobs — and
terrible at chat: every turn pays subprocess startup, and the user
stares at a spinner. An in-process chat model is the opposite: instant
first token, but you don't want it grinding through a 20-minute
research job inside your request handler. The framework's answer is
two *execution tiers over one set of definitions*: the same
`AgentDefinition` primitives drive a snappy in-process chat agent
(interactive tier) and a fire-and-forget compiled worker (opencode
tier) — and the chat agent's "heavy" tool is simply *dispatch to the
worker*.

## What you'll build

- A **worker**: a compiled `deep-research` opencode agent (built the
  usual way — see the [triage tutorial](support-triage-bot.md)).
- A **chat concierge**: an in-process interactive agent on a local
  OpenAI-compatible model that answers instantly, and calls a
  `start-research` tool that spawns the worker asynchronously and
  reports back a job handle.

Prerequisites: [installation](../getting-started/installation.md), the
`opencode` CLI, the `openai` Python package, and a local
OpenAI-compatible endpoint (e.g. vLLM at `http://localhost:8000/v1`).
Built on the `open_agent_compiler.interactive` APIs plus
`examples/31_spawn_agent`.

## Step 1 — the worker (kept deliberately simple)

Any compiled primary agent works. Define and compile a `deep-research`
agent exactly as in the earlier tutorials
(`AgentRegistry` → `TemplateTree` → `CompileScript`), with a prompt
like "research the topic thoroughly and write a structured report".
Compile it into `build/` — the build ships
`scripts/opencode_manager.py`, the dispatcher the spawn tool shells
out to. That directory is where you'll run the chat process from.

## Step 2 — the chat agent definition

`chat_agent.py`. The concierge is a normal `AgentDefinition`; its one
tool is declared with just a header, because on the interactive tier
*you* execute tools in-process — the model only needs the name and
description to decide when to call it:

```python
from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition, AgentHeader, ModelPreset, SamplingDefaults,
    SpawnAgentInput, SpawnAgentTool, ToolDefinition, ToolDefinitionHeader,
    VariantSpec,
)
from open_agent_compiler.interactive import build_interactive_spec, run_interactive


def start_research_tool() -> ToolDefinition:
    return ToolDefinition(header=ToolDefinitionHeader(
        name="start-research",
        description=(
            "Kick off a deep research job on the worker fleet. Returns"
            " immediately with a job id; the report is delivered when done."
        ),
        usage_explanation_long=(
            "Call when the user asks for anything that needs real research"
            " (surveys, comparisons, reports). Pass the topic as `prompt`."
        ),
        usage_explanation_short="dispatch a heavy research job",
        rules=["Never attempt deep research inline — always dispatch."],
    ))


def concierge() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="concierge", name="concierge",
            description="Snappy chat front-end that delegates heavy work.",
        ),
        usage_explanation_long=(
            "Answers quick questions directly. For heavy requests it calls"
            " start-research and tells the user the job id it will report on."
        ),
        usage_explanation_short="chat front-end",
        system_prompt=(
            "You are a fast, friendly assistant.\n"
            "- Small questions: answer directly in 1-3 sentences.\n"
            "- Anything needing real research: call start-research with the"
            " topic, then tell the user the job has started and quote the"
            " returned job id. Never fake research results."
        ),
        extra_tools=[start_research_tool()],
    )
```

## Step 3 — the live profile and the spec

The interactive tier resolves the model through a *live* `VariantSpec`
— a different provider resolution than the worker compile, from the
same definition. `provider_options` carries the endpoint; the
`extra_body` entry disables Qwen's thinking mode, which otherwise
returns empty content on vLLM:

```python
LIVE = VariantSpec(
    name="live", postfix="",
    preset=ModelPreset(
        name="local-qwen",
        provider="local-vllm-remote", model_id="qwen35-27b",
        sampling=SamplingDefaults(temperature=0.4),
        provider_options={
            "base_url": "http://localhost:8000/v1",
            "extra_body": '{"chat_template_kwargs": {"enable_thinking": false}}',
        },
    ),
)

SPEC = build_interactive_spec(agent=concierge(), live_profile=LIVE)
```

## Step 4 — the tool runner: dispatch to the worker

When the model calls `start-research`, the runner spawns the compiled
worker asynchronously via `SpawnAgentTool` and returns a `TaskHandle`
summary as the tool result — the chat turn never blocks on the job:

```python
def tool_runner(name: str, args: dict) -> str:
    if name == "start-research":
        out = SpawnAgentTool().execute(SpawnAgentInput(
            agent_name="deep-research",
            prompt=str(args.get("prompt") or args.get("input") or ""),
            spawn_async=True,
        ))
        return (
            f"research job started: run_id={out.task.run_id}"
            f" status={out.task.status} poll_url={out.task.poll_url}"
        )
    return f"ERROR: unknown tool {name}"
```

## Step 5 — the chat loop

`run_interactive` owns the whole turn — system prompt, history, tool
round-trips — and brackets every tool call with events on the sink, so
the UI can show "working on it" the moment a dispatch starts:

```python
def main() -> None:
    def on_event(event) -> None:
        print(f"  [{event.kind}] {event.source} {event.payload}")

    history: list[dict] = []
    while True:
        user = input("you> ").strip()
        if user in ("", "quit"):
            break
        result = run_interactive(
            SPEC, user,
            tool_runner=tool_runner,
            sink=on_event,
            history=history,
            max_tool_rounds=4,
        )
        history = result.messages[1:]  # drop the system message
        print(f"bot> {result.output_text}\n")


if __name__ == "__main__":
    main()
```

## Run it

From the worker's build directory (so the spawn tool finds
`scripts/opencode_manager.py`):

```bash
uv run python chat_agent.py
```

```
you> what's a bloom filter?
bot> A Bloom filter is a compact probabilistic set: it can say "definitely
not present" or "probably present" using a few hash functions over a bit
array. You trade a small false-positive rate for tiny memory use.

you> compare the main vector databases for a 100M-embedding workload
  [tool.start] concierge {'tool': 'start-research', 'args': {'prompt': ...}}
  [tool.end] concierge {'tool': 'start-research', 'result': 'research job
    started: run_id=agent_run_3f9c2a status=running poll_url=/runs/...'}
bot> That needs proper research, so I've started a job — id
agent_run_3f9c2a. I'll report back with the full comparison when it's done.
```

The first answer streams back in well under a second from the local
model; the second returns just as fast *while the worker grinds away in
its own opencode session*. Every dispatch lands in
`result.tool_calls` as a `ToolCallRecord`, so the same probes and
evaluators that score worker runs can score live chat turns.

Prefer assembling your own LangGraph/LCEL loop with token streaming?
The LangChain binding consumes the identical spec:
`build_chat_model(spec, streaming=True)` and `to_langchain_tools(spec,
...)` from `open_agent_compiler.interactive.bindings.langchain_binding`
(install the `open-agent-compiler[langchain]` extra).

## Why it works

Both tiers are projections of the same `AgentDefinition`: the compiler
projects it to opencode artifacts for unattended heavy work, and
`build_interactive_spec` projects it (through a live `VariantSpec`) to
an in-process spec a chat loop can run with instant feedback. Because
the tiers share every primitive — definitions, tools, presets, tests —
"fast chat + slow worker" is not two codebases glued together but one
agent tree with two runtimes, joined by an ordinary tool call.

## Going further

- [Execution tiers](../concepts/execution-tiers.md) — the flagship
  concept in depth.
- [Interactive tier guide](../guides/interactive-tier.md) — bindings,
  event sinks, structured output via `output_schema`.
- `examples/29_long_running_task` and `examples/35_fastapi_dispatch` —
  `TaskHandle` polling and the `/runs/{run_id}/await` pattern for
  delivering the finished report back into the chat.
