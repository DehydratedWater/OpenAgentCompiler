"""authoring-agents skill — how to design an agent definition properly."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Authoring agents

An `AgentDefinition` is what you ship. It compiles to a single
`agent_<slot>.md` file under `build/.opencode/agents/`. The OpenCode
runtime reads that file and uses the YAML frontmatter (permissions,
model, mode) plus the markdown body (system prompt) to drive the LLM.

## When to use which prompt mechanism

Three knobs control the body of the compiled prompt:

1. **`system_prompt`** — a free-form string. Use this when the agent's
   job is open-ended ("you are a helpful assistant", "you triage
   tickets"). Fastest to write, most flexible at runtime.

2. **`workflow`** — a list of `WorkflowStepDefinition`. Use this when
   the agent must execute a *procedure* on every message (multi-step
   plans, decision trees, route-and-handoff orchestrators). The
   compiler builds a MANDATORY WORKFLOW block with STEP 0 task list,
   per-step gates / criteria / tools / subagent invocations /
   mark-done bash, and a final checklist.

3. **Both** — set both fields. The `system_prompt` is prepended above
   the MANDATORY WORKFLOW so the system_prompt frames the workflow.

Composition rules:

| workflow set? | system_prompt set? | Result body |
|---------------|--------------------|------------|
| no            | no                 | `usage_explanation_long` (fallback) |
| no            | yes                | `system_prompt` |
| yes           | no                 | workflow render |
| yes           | yes                | `system_prompt` + workflow render |

When workflow is set, `preamble` and `postamble` fields wrap the
workflow block (preamble before MANDATORY WORKFLOW header, postamble
after FINAL CHECKLIST).

## Modes: primary vs subagent

- `agent_mode = "primary"` (set on AgentVariant) — the agent the user
  directly invokes. Can use the Task tool to delegate to other agents.
  Uses todowrite/todoread for progress.
- `agent_mode = "subagent"` — only invokable from a parent's Task call.
  CANNOT delegate further (one-level fan-out). Uses the bundled
  `subagent_todo.py` file-based todo because subagents don't have
  todowrite/todoread access.

In the registry, the slot named `"primary"` always compiles in primary
mode; every other slot compiles in subagent mode. To have multiple
primaries in one tree, register multiple `CompilationConfig`s and
compile them separately.

## todo_mode: strict / lazy / none

Three modes for how todo tracking is enforced in the workflow prompt:

- `strict` (default) — full STEP 0 task list + per-step mark-done bash.
  Use for agents where audit trails matter (production orchestrators).
- `lazy` — STEP 0 task list once, no per-step marks. Use when the
  agent should focus on the work, not the bookkeeping.
- `none` — no todo bash, no STEP 0. Use for one-shot agents whose
  whole behavior fits in a single workflow step.

## Workspace sandboxing

Set `workspace=".agent_workspace/{name}"` on the AgentDefinition to
give the agent an isolated FS sandbox via `workspace_io.py`. The
compiler emits a STEP 0a init block; the agent saves a `run_id` and
passes it to every subsequent write/read/list/delete. The SECURITY
POLICY block also forbids file creation via bash so the agent can't
escape the sandbox.

## Subagent references

Declare subagents on `AgentDefinition.subagents` as a list of
`AgentHeader`. Each header can carry an explicit `mode` ("subagent"
for Task-tool invocation or "primary" for opencode_manager.py bash
dispatch); `mode=None` defaults to "subagent". The compiler:

- Renders Available Subagents section in the prompt.
- Adds appropriate permission entries.
- Lists each in the SECURITY POLICY ALLOWED block.
- Auto-orders subagents in compilation via the build_graph
  (parents before children).

## Common mistakes

1. **Defining a workflow but forgetting to register subagents.** The
   workflow can reference subagent names in step.subagents, but if the
   agent's `subagents` field is empty, the SECURITY POLICY will forbid
   invocation. Add a subagent to both places.

2. **Setting `workspace` AND `tool_permissions.write=True`.** Workspace
   mode disables direct writes; the permission would be redundant and
   confusing. Pick one.

3. **Forgetting to bump model selection per agent.** All agents in a
   compile pass use the registry's bound preset by default. To use a
   different model for one agent, either register it with a different
   `ModelPreset` or compile with a `VariantSpec` that overrides.

## Dual-compile: same agent as both subagent AND primary

A subagent (any slot not named `"primary"`) compiles to `mode:
subagent` and is reachable only through Task delegation. You CAN'T
invoke it via `opencode run --agent <name>` — opencode prints
"agent X is a subagent, falling back to default agent".

To make a worker reachable both ways (subagent via Task AND direct
via opencode run / opencode_manager dispatch / autoresearch eval),
set `also_compile_as_primary=True` on its slot:

```python
reg.register_template(TemplateTree(
    name="default",
    slots=[
        TemplateSlot(name="primary", default_agent_id=research_id),
        TemplateSlot(
            name="transcript-scorer",
            default_agent_id=scorer_id,
            also_compile_as_primary=True,  # ← dual-compile
        ),
    ],
))
```

The compiler emits BOTH `<name>.md` (subagent for Task) AND
`<name>-primary.md` (primary mode, directly callable). The MCP
server scaffold registers both variants automatically.

Used by every worker in a media-tracking consumer project. Required for the
autoresearch pattern in `improvement-loop` (eval driver needs to
invoke an isolated candidate as a primary).

## `register_with_improvements` — composable improvement merge

For any agent you want auto-improvement on, use
`register_with_improvements` instead of `register_agent`. It walks
the AgentDefinition tree (agent + skills + tools through skills +
extra_tools) and merges promoted snapshots from `.oac/promoted/`.
No-op on a fresh project; after `oac improve` + `oac promote`,
the improvements ship transparently. See `improvement-loop` skill.

See also: `authoring-tools`, `variants-and-profiles`,
`improvement-loop`, `prompt-structure`, `tool-variants`,
`sandboxed-scripting` (for agents that need to author scripts
without bash).
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="authoring-agents",
        description=(
            "How to design AgentDefinition: system_prompt vs workflow vs"
            " composition, primary vs subagent modes, todo_mode, workspace"
            " sandboxing, common mistakes."
        ),
        body_markdown=BODY,
        tools_hint=("AgentDefinition", "WorkflowStepDefinition"),
    )
