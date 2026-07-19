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
  Claude Code, Pi, and Codex agent formats, plus an in-process
  interactive tier.
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

**New here?** Follow the path:

1. [Installation](getting-started/installation.md) — get `oac` running.
2. [Your First Agent](getting-started/first-agent.md) — define, compile,
   and run an agent in ten minutes.
3. [Philosophy & Assumptions](concepts/philosophy.md) — the mental model
   behind the framework.
4. [Execution Tiers](concepts/execution-tiers.md) — the fast/slow split:
   in-process interactive agents vs compiled long-running workers.

**Want to see features earn their keep?** Each
[tutorial](tutorials/index.md) is a mini-project built around one
feature: a [triage bot](tutorials/support-triage-bot.md) (agent trees),
a [database reporting tool](tutorials/database-reporting-tool.md)
(tools + mocked tests), [one agent on three
models](tutorials/one-agent-three-models.md) (variants), a
[self-improving agent](tutorials/self-improving-agent.md) (the
improvement loop), and [fast chat + slow
worker](tutorials/fast-chat-slow-worker.md) (execution tiers).

**Building something specific?** The [guides](guides/tools.md) cover
tools, workflows, skills, variants, testing, the improvement loop, and
the interactive tier; the [dialect pages](dialects/opencode.md) cover
each compile target; the [CLI reference](reference/cli.md) and
[troubleshooting](reference/troubleshooting.md) round it out.

**Prefer one long read?** The original
[all-in-one guide](dev-guide.md) still exists, and the field lessons —
[optimize the real goal](lessons/optimize-the-real-goal-not-text-correctness.md),
[thinking models & scoring](lessons/thinking-models-and-opencode-scoring.md),
[tuning a local agent fleet](lessons/tuning-a-local-agent-fleet.md) —
capture hard-won production experience.
