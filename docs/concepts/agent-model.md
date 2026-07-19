# The agent model

This page dissects `AgentDefinition` — the single Pydantic model everything
else compiles from — field by field, starting from a complete working example.

Every field below is verified against
`open_agent_compiler/model/core/agent_model.py`. If you only remember one
thing: **only `header`, `usage_explanation_long`, and
`usage_explanation_short` are required.** Everything else defaults to "off".

## A complete definition, annotated

```python
from open_agent_compiler import (
    AgentDefinition, AgentHeader, AgentToolPermissions,
    Criterion, Route, WorkflowStepDefinition,
    CapabilityTest,
)

researcher = AgentDefinition(
    # WHO this agent is (identity + how it's referenced)
    header=AgentHeader(
        agent_id="researcher",
        name="researcher",
        description="Researches a topic and drafts a sourced summary.",
    ),

    # WHAT it's for — required, two lengths (see below for why)
    usage_explanation_short="researches topics",
    usage_explanation_long=(
        "Given a topic, gathers material, drafts a summary with sources, "
        "and revises until the draft passes review."
    ),

    # HOW it behaves — the core prompt...
    system_prompt="You are a meticulous researcher. Cite every claim.",

    # ...and/or a structured, enforced procedure
    workflow=[
        WorkflowStepDefinition(
            id=1, name="Draft",
            instructions="Write a first draft with inline sources.",
        ),
        WorkflowStepDefinition(
            id=2, name="Review",
            instructions="Assess the draft against the brief.",
            evaluates=(Criterion(
                name="quality",
                question="Is the draft good enough to ship?",
                possible_values=("yes", "no"),
            ),),
            routes=(Route(criteria_name="quality", value="no", goto_step=1),),
            subagents=("critic",),
        ),
    ],
    todo_mode="strict",                     # bookkeep progress per step

    # WHAT it may touch
    tool_permissions=AgentToolPermissions(read=True, write=True),
    subagents=[AgentHeader(agent_id="critic", name="critic")],

    # PROOF it works — tests travel with the definition
    capability_tests=[CapabilityTest(
        name="researcher-cannot-edit",
        description="Write access without edit — check the compiled artifact.",
        must_not_have_tools=("edit",),
    )],
)
```

Registration binds it to a model:

```python
from open_agent_compiler import AgentRegistry, ModelParameters

reg = AgentRegistry()
agent_id = reg.register_agent(
    "researcher", researcher,
    ModelParameters(model_name="anthropic/claude-sonnet-4-5", temperature=0.7),
)
```

Note what is *not* on the definition: the model. `ModelParameters(model_name,
temperature)` is supplied at registration, so the same definition registers
under many models. Now the dissection.

## Identity: `header`

`AgentHeader(agent_id, name, description, mode)`. The `agent_id` is how other
things point at this agent — subagent references, template slots. `mode`
(`"primary"` | `"subagent"`) matters mostly on *references*: listing a header
in another agent's `subagents` with `mode="primary"` invokes it as a
standalone primary instead of via the runtime's Task tool. Leave it `None` and
it defaults to `"subagent"` at render time.

## Purpose: `usage_explanation_long` / `usage_explanation_short`

Both required, and deliberately two lengths. The **short** form is what
*other agents* see — when this agent appears as a subagent, its parent's
prompt needs a one-line "when to dispatch here". The **long** form is the full
human/agent documentation, and doubles as the prompt body fallback when both
`system_prompt` and `workflow` are empty. Write the short form as a routing
hint, the long form as a job description.

## Behavior: `system_prompt` vs `workflow`

These compose rather than compete:

- **`system_prompt` alone** — the entire body of the compiled agent file.
  Right for conversational or judgment-driven agents.
- **`workflow` alone** — a list of `WorkflowStepDefinition`s rendered as a
  numbered MANDATORY WORKFLOW: per-step instructions, `evaluates` criteria,
  conditional `routes` (loop back on `quality == "no"`), `subagents` spawned
  at a step, `marks_done` todo bookkeeping, and optional `gate`s. Right for
  repeatable multi-step jobs.
- **Both** — `system_prompt` is *prepended* before the workflow block:
  persona first, procedure second.

Workflow-only trimmings: `preamble` (between prompt and workflow header),
`postamble` (after the final checklist), and `inline_skills` (render skills as
full inline bash docs vs a name-reference list). All three are ignored when
`workflow` is empty.

`prompt_sections` is the optimizable form of `system_prompt`: an ordered list
of named sections, each flagged required and/or mutable. When set,
`system_prompt` is *derived* from it, and the improvement loop rewrites one
section at a time instead of gutting the whole prompt — see
[Improvement loop](../guides/improvement-loop.md).

`todo_mode` (`"strict"` default | `"lazy"` | `"none"`) controls progress
tracking: strict adds a STEP-0 task-list bootstrap plus per-step completion
marks; lazy keeps the task list but drops the marks; none removes todo
tooling entirely.

`workspace` (e.g. `".agent_workspace/{name}"`) gives the agent a sandbox
directory convention, adding a workspace-init step to the workflow prompt.

## Capabilities: `extra_tools`, `skills`, `subagents`

- **`extra_tools`** — `ToolDefinition`s: bash tools and/or JSON ScriptTools
  the compiler documents in the prompt, allowlists in permissions, and writes
  into `scripts/`. Companion knobs: `default_tool_format`
  (`"bash"` | `"json"` | `"both"`) and per-tool `tool_format_overrides`, with
  `chosen_format()` falling back to whatever contract a tool actually carries.
  See [Tools](../guides/tools.md).
- **`skills`** — `SkillDefinition(name, description, usage_explanation_long/short,
  rules, workflow_steps, positive_examples, negative_examples)`: reusable
  capability blocks compiled into prompt and frontmatter.
- **`subagents`** — `AgentHeader` *references* (not nested definitions).
  Each referenced agent is registered separately and given its own template
  slot; the reference is what wires dispatch. See
  [Registry and compilation](registry-and-compilation.md).

## Boundaries: `tool_permissions`, `mcp_servers`

`ToolPermissions(read, write, edit, mcp)` — four booleans, all default
`False`, exported as `AgentToolPermissions` from the package root. They
compile to *both* runtime enforcement (e.g. OpenCode's `permission:` block)
and a SECURITY POLICY prompt section, so enforcement and agent awareness
never drift. `mcp_servers` is the finer-grained sibling: per-server
`MCPServerDefinition(name, allowed_tools=[...])` allowlists (empty
`allowed_tools` = every tool on that server).

## Routing: `model_class`

A symbolic label (`"fast"`, `"analytical"`, …) read by `SplitProfile` at
compile time to pick a per-agent model preset — how a fleet sends cheap slots
to a local model and hard slots to a frontier model in one compile. Ignored
unless the active variant is a `SplitProfile`. See
[Variants and profiles](../guides/variants-and-profiles.md).

## Proof: `agent_tests`, `capability_tests`, `tool_tests`

Embedded tests, run by `oac test`: `CapabilityTest` (pure introspection of
the compiled artifact — `must_have_tools`, `must_not_have_tools`,
`must_have_skills`, bash-pattern checks; no model calls), `ToolTest` (drives
a tool handler or its mock, `mock_profile` selects bindings), `AgentTest`
(end-to-end scenarios with evaluators). Details in
[Testing](../guides/testing.md).

One near-miss to know: `also_compile_as_primary` is **not** an
`AgentDefinition` field — it lives on `TemplateSlot` (deployment shape, not
behavior), and flows onto the resolved variant at compile time.

Next: [Registry and compilation](registry-and-compilation.md) — how
definitions become files on disk.
