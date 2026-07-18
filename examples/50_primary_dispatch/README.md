# 50 primary-dispatch — primary → primary via opencode_manager

A coordinator agent that spawns a **separate primary agent** via the
bundled `opencode_manager.py` bash dispatcher instead of the Task tool.

```
math-coordinator (primary, glm-5.1)
   ↓ bash: opencode_manager.py run --agent number-cruncher "<sub-question>"
number-cruncher  (primary, glm-4.5-air)  — spawned as a fresh session
```

## Why primary→primary?

Task-tool subagents share the parent's context window — every tool
call the child makes shows up in the parent's transcript. For workers
that need to do a lot of work (or recursive delegation of their own),
that explodes the parent's tokens.

Primary-mode dispatch spawns the worker as a fresh `opencode run`
session. The worker has its own context, can have its own subagents,
and only its final output comes back to the coordinator.

## Build

```bash
uv run python examples/50_primary_dispatch/build_agents.py
```

Produces:
```
build/.opencode/agents/primary.md           (math-coordinator, primary)
build/.opencode/agents/number-cruncher.md   (number-cruncher, primary)
build/scripts/opencode_manager.py           (bundled dispatcher)
build/scripts/subagent_todo.py
build/scripts/workspace_io.py
```

## Inspect coordinator permissions

```bash
grep -A 2 "permission" build/.opencode/agents/primary.md | head -10
```

You'll see:
```
permission:
  '*': deny
  bash:
    '*': deny
    uv run scripts/opencode_manager.py run --agent *: allow
```

That allowlist is what makes the dispatcher invocation possible.

## Invoke

```bash
cd build
opencode run --agent primary \
    "If I have 12 apples and give 4 to each of 3 friends, how many do I keep?"
```

The coordinator decomposes the problem, calls
`opencode_manager.py run --agent number-cruncher "..."` for each
sub-question, gets the numbers back, and assembles the final answer.

## What's exercised

- **Primary-mode subagent reference** — `AgentHeader(..., mode="primary")`.
- **Bash allowlist auto-emit** — the new permission rule that lets the
  coordinator invoke the dispatcher.
- **Bundled `opencode_manager.py`** — copied into `build/scripts/`
  automatically by the auto-include rule.
- **Manual agent_mode override post-resolve** — the worker's slot name
  isn't `primary`, so the registry's default rule would mark it as
  subagent; the build script `model_copy(update={"agent_mode":
  "primary"})` corrects that.
