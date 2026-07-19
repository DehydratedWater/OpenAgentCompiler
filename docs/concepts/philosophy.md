# Philosophy

This page states the assumptions the framework is built on — explicitly, one
by one, each with the *why* behind it and what it means for how you work.
Everything else in the docs is a consequence of these five ideas.

## 1. It's a compiler, not a runtime

Your agents are **data**: Pydantic models (`AgentDefinition`, `ToolDefinition`,
`SkillDefinition`, …) that describe behavior. The framework does not execute
them — it *compiles* them into whatever artifact a target runtime needs: a
`.opencode/agents/*.md` tree for OpenCode, a `.claude/` tree for Claude Code, a
`.pi/agents/*.md` tree for Pi, or an in-process `InteractiveAgentSpec` for a
chat binding.

**Why.** Runtimes churn. Prompt formats, permission syntax, and tool-calling
conventions differ per runtime and change under you. If your agents *are* the
runtime's config files, every runtime change is a hand-migration across every
agent. If your agents are typed data and the framework owns the artifact
format, a runtime change is a compiler change — made once, applied everywhere
on the next build.

**Consequence.** You never hand-edit anything under `build/`. Compiled output
is disposable, regenerated from the registry (`clean=True` wipes it). The
source of truth is always the Python definition. It also means artifacts are
*readable back*: `load_compiled_agent` parses a compiled `.md` into a
`CompiledAgent`, which is what capability tests introspect.

## 2. Define once, compile everywhere

One `AgentDefinition` serves every target. The same definition that compiles
to an OpenCode worker also compiles to Claude Code, to Pi, and — via
`build_interactive_spec` — to an in-process streaming chat agent.

**Why.** Real applications need both a slow lane (long-running autonomous
workers) and a fast lane (sub-second conversational responses), often for the
*same* logical agent. Maintaining two hand-written variants guarantees drift:
the chat prompt learns something the worker prompt never hears about.

**Consequence.** Runtime-specific scaffolding (bash invocation syntax, todo
bootstrapping, security-policy blocks) is the *dialect's* job, injected at
compile time — you never write it into `system_prompt`. Keep the definition
about intent; let each compiler add its runtime's plumbing. See
[Execution tiers](execution-tiers.md) and the dialect pages
([opencode](../dialects/opencode.md), [claude-code](../dialects/claude-code.md),
[pi](../dialects/pi.md)).

## 3. Typed Python over YAML

Every definition is a Pydantic model. Registration and compilation validate
eagerly: an unknown agent id in a slot, a config pointing at a missing
template, a dialect name that isn't registered — all raise at
`create_compilation_config()` / `CompileScript` construction time, not when an
agent misbehaves in production.

**Why.** YAML agent configs fail at the worst possible moment: at runtime, in
front of a user, often silently (a typo'd key is just ignored). Typed models
fail loudly at build time, and your editor autocompletes the schema instead of
you memorizing it.

**Consequence.** Factories are ordinary Python functions returning an
`AgentRegistry`, so you get loops, composition, and conditionals for free —
building fifty agent variants is a `for` loop over `ModelPreset`s, not fifty
files. And because definitions are data, they can be diffed, snapshotted, and
mutated programmatically — which assumption 5 depends on.

## 4. Tests live with the agents, and run on mocks

Tests are fields *on* the definitions: `agent_tests`, `capability_tests`, and
`tool_tests` sit directly on `AgentDefinition` (and tool-level tests on
`ToolDefinition`). Every tool ships a `MockResponse`, and a `MockProfile`
selects mock bindings for a whole build. `uv run oac test` runs the suite
green with **zero credentials**.

**Why.** Tests stored elsewhere rot: rename an agent and its tests silently
stop covering it. Tests requiring live credentials don't run in CI, which
means they don't run. Co-located, mock-backed tests travel with the definition
through every compile, variant, and improvement cycle.

**Consequence.** "Every tool ships a mock" is a design rule, not a suggestion
— a tool without a mock makes the whole suite credential-dependent. It also
gives you three cheap layers: capability tests introspect compiled artifacts
(no model calls at all), tool tests drive handlers or mocks, and agent tests
run full scenarios with evaluators. See [Testing](../guides/testing.md).

## 5. Agents are optimizable artifacts

Because an agent is data, every part of it — prompt, prompt *sections*, tool
docs, temperature — is a **component** that can be mutated, scored against
probes, and promoted. The improvement loop is: mutate → compile → evaluate →
keep the frontier → snapshot → `oac promote` → next compile picks the winner
up (via `register_with_improvements`). `prompt_sections` makes this
fine-grained: a rich multi-section prompt is improved *section by section*,
never gutted and rewritten as one blob.

**Why.** Hand-tuning prompts doesn't scale past a handful of agents, and it
definitely doesn't scale across model variants — the phrasing that steers one
model is noise to another. An automated loop tunes each (agent × model) pair
against measurable criteria.

**Consequence.** Write agents *expecting* them to be optimized: structured
sections over monolithic prompts, evaluators over vibes. And heed the field
lesson — **optimize the real goal, not text plausibility**. A production loop
once scored agents on their prose while actual delivery happened through a
tool call; the optimizer polished the prose and silently dropped the
load-bearing tool call. Gate evaluators on the production contract (tool
called, artifact emitted), not on how good the text looks. Full story:
[Optimize the real goal, not text correctness](../lessons/optimize-the-real-goal-not-text-correctness.md);
mechanics: [Improvement loop](../guides/improvement-loop.md).

## The shape that falls out

```
     typed definitions          compiler           runtimes
  ┌──────────────────────┐   ┌───────────┐   ┌──────────────────────┐
  │ AgentDefinition       │   │ dialects: │   │ .opencode/ .claude/  │
  │  + tools + skills     ├──▶│ opencode  ├──▶│ .pi/  (workers)      │
  │  + tests + workflow   │   │ claude,pi │   │ InteractiveAgentSpec │
  └──────────┬───────────┘   └───────────┘   │  (in-process chat)   │
             │                    ▲          └──────────────────────┘
             │   mutate/evaluate  │
             └────────────────────┘
              improvement loop (promoted snapshots feed the next compile)
```

Definitions in, artifacts out, and a feedback loop that treats the definitions
themselves as the thing being optimized.

Next: [The agent model](agent-model.md) dissects `AgentDefinition` field by
field, or jump straight to [your first agent](../getting-started/first-agent.md).
