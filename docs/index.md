# open-agent-compiler

**Define agents once, as typed Python. Compile them to any agent runtime.
Test them with mocks. Improve them with closed-loop optimization.**

`open-agent-compiler` is a Python-first agent framework built around a
compiler, not a runtime: agents are declarative Pydantic definitions —
system prompts, tools, skills, workflows, permissions, subagents, and
tests — and the framework turns that single source of truth into whatever
each target runtime needs.

```
                ┌────────────────────────────────────────────┐
                │        AgentDefinition (Pydantic)          │
                │  prompt · tools · skills · workflow ·      │
                │  permissions · subagents · tests           │
                └──────────────┬─────────────────────────────┘
                               │ compile
      ┌────────────────────────┼────────────────────┬──────────────────┐
      ▼                        ▼                    ▼                  ▼
.opencode/agents/*.md   .claude/agents/*.md   .pi/agents/*.md   InteractiveAgentSpec
(OpenCode runtime)      (Claude Code)         (Pi agents)       (LangChain runnable)
```

## Install

```bash
pip install open-agent-compiler
# or
uv add open-agent-compiler
```

## Highlights

- **Multi-dialect compiler** — one agent tree compiles to OpenCode,
  Claude Code, and Pi agent formats, plus an in-process interactive tier.
- **Embedded testing** — capability, tool, and agent tests live next to
  the definitions and run against mocks, so CI never needs credentials.
- **Improvement loop** — mutate prompts and parameters, evaluate against
  probes, keep what scores better, and promote winners — per model, in
  parallel.
- **Scaffolding** — `oac init` generates a full project (optionally with
  Docker, FastAPI, Postgres, cron, or a per-client personalized SaaS
  shape).
- **`oac` CLI** — compile, introspect, test, improve, and promote from
  the terminal.

## Where to go next

- [Developer Guide](dev-guide.md) — the complete tour, from first agent
  to improvement loops.
- [Pi Agent Dialect](pi-agent-dialect.md) — compiling to the Pi runtime.
- [Retrieval Testing](retrieval-testing.md) — fact-recall evaluation
  packs.
- Field lessons: hard-won notes from production deployments —
  [optimize the real goal](lessons/optimize-the-real-goal-not-text-correctness.md),
  [thinking models & scoring](lessons/thinking-models-and-opencode-scoring.md),
  [tuning a local agent fleet](lessons/tuning-a-local-agent-fleet.md).
- [Examples](https://github.com/DehydratedWater/OpenAgentCompiler/tree/main/examples)
  — 20+ runnable examples from hello-world to per-model optimization
  fleets and SaaS scaffolds.
