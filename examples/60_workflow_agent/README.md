# 60 workflow_agent — full Phase 3 workflow grammar

A ticket-triage agent exercising the **entire** WorkflowStepDefinition
surface in one compiled prompt:

- 4 numbered steps with names + instructions
- A `Criterion` with `possible_values` (step 1: severity ∈ low/medium/high)
- A `Gate` (step 2 only runs when `severity=high`)
- `Route`s from step 2 to alternate steps based on severity
- `marks_done` on every step (per-step `subagent_todo.py update` lines
  render in strict mode)
- `preamble` + `postamble` wrapping the workflow block
- `todo_mode="strict"` — STEP 0 task list + per-step marks + final
  verification block
- `workspace=".agent_workspace/{name}"` — STEP 0a workspace_io.py init

## Build

```bash
uv run python examples/60_workflow_agent/build_agents.py
```

Produces `build/.opencode/agents/primary.md` (~5KB rendered prompt) +
`build/scripts/subagent_todo.py` + `build/scripts/workspace_io.py`
(auto-included because the workflow references them).

## Inspect the compiled prompt

```bash
less examples/60_workflow_agent/build/.opencode/agents/primary.md
```

Walk top-to-bottom and you'll see, in order:
1. The preamble ("# Support Ticket Triage…")
2. `## MANDATORY WORKFLOW` header with the "use subagent_todo.py" hint
3. `### STEP 0a: Initialize Workspace Session` (workspace_io.py init)
4. `### STEP 0: Initialize Progress Tracking` (subagent_todo.py init +
   one add command per todo)
5. `### STEP 1: ClassifySeverity` — instructions + an `**Evaluate the
   following criteria:**` block listing severity with its possible
   values + the per-step mark-done bash command
6. `### STEP 2: EscalateIfHigh` — a single `**Condition:**` block
   (gate), instructions, the route table ("If severity=low → STEP 4"),
   the mark-done command
7. `### STEP 3: DraftResponse` — a `**Use these tools:**` block
   listing rule-checker, instructions, mark-done
8. `### STEP 4: Finalise` — instructions + mark-done
9. `## FINAL CHECKLIST` with the strict-mode verification command +
   the "ASK YOURSELF" todo list
10. The postamble
11. `## SECURITY POLICY` (workspace-restricted writes, no MCP, etc.)

## Invoke

```bash
cd examples/60_workflow_agent/build
opencode run --agent primary \
    "Production database has been down for 20 minutes. Can't reach the on-call."
```

The agent should classify severity=high, walk steps 0a/0/1/2/3/4 in
order, mark each todo done, run the final checklist verification,
and produce a labelled response.

## What's exercised

Every optional field of `WorkflowStepDefinition`:
- `gate` (Gate / GateCheck)
- `evaluates` (Criterion with possible_values)
- `routes` (Route to alternate steps)
- `marks_done` (per-step todo marks)
- `tool_uses` (ToolUse reference)
- `instructions` (free-form prose)

Plus the prompt-shell options:
- `todo_mode="strict"`
- `workspace` substitution
- `preamble` + `postamble`

Auto-include of bundled scripts (Phase 4.4): the strict todo_mode
pulls `subagent_todo.py`; the workspace pulls `workspace_io.py`.
