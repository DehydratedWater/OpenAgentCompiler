# 40 subagents — Task-tool orchestration

An **orchestrator** that delegates to two **Task-tool subagents**:

```
primary (orchestrator, glm-4.5-air)
   ├── Task → summarizer (subagent, glm-4.5-air)
   └── Task → critic     (subagent, glm-5.1)
```

The orchestrator's prompt explicitly tells it: never summarise / critique
inline; always delegate via the Task tool. The final response is the
two subagent outputs labelled `SUMMARY:` and `COUNTERPOINT:`.

## Build

```bash
uv run python examples/40_subagents/build_agents.py
```

Produces:
```
build/.opencode/agents/primary.md        (orchestrator, mode=primary)
build/.opencode/agents/summarizer.md     (mode=subagent)
build/.opencode/agents/critic.md         (mode=subagent)
```

## Invoke

```bash
cd examples/40_subagents/build
opencode run --agent primary \
    "Containers are strictly better than VMs for production workloads — discuss."
```

opencode loads the orchestrator, which uses the Task tool to spawn the
two subagents in sequence. The final reply has both labelled sections.

## What's exercised

- **`AgentDefinition.subagents`** — `AgentHeader` references with
  `mode="subagent"`. The compiled orchestrator's frontmatter +
  SECURITY POLICY block list each as an allowed Task target.
- **Multi-slot template** — three slots, three compiled .md files,
  one per agent. Slot named "primary" gets `mode: primary`; the others
  get `mode: subagent` per the registry's resolve rule.
- **Per-agent model assignment** — orchestrator + summarizer use
  glm-4.5-air; critic uses glm-5.1. Different sampling temperatures.
- **The whole "Available Subagents" + SECURITY POLICY ALLOWED**
  prompt block — visible in `primary.md` after compile.

## Inspect

```bash
sed -n '/Available Subagents/,/SECURITY POLICY/p' build/.opencode/agents/primary.md
```

Look for the `### summarizer — …` and `### critic — …` sections.
