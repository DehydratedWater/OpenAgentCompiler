# Workflows and subagents

In this guide you'll build a procedure-following agent from
`WorkflowStepDefinition` steps, then compose an orchestrator tree where a
primary agent delegates to focused subagents — including the dual-compile
trick that makes one worker reachable both via the Task tool and by direct
invocation, and the spawn patterns for primary-to-primary dispatch.

## 1. Define a workflow

Use `workflow=[WorkflowStepDefinition(...)]` when the agent must execute a
*procedure* on every message (use plain `system_prompt` for open-ended jobs;
set both and the prompt is prepended above the workflow). Each step's fields
are rendered as prompt hints — criteria to evaluate, gates, conditional
routes, tool notes, subagent invocations, and todo bookkeeping:

```python
from open_agent_compiler import (
    Criterion, Gate, GateCheck, Route, ToolUse, WorkflowStepDefinition,
)

workflow = [
    WorkflowStepDefinition(
        id=1, name="ClassifySeverity",
        todo_name="classify",
        todo_description="Pick severity ∈ {low, medium, high}.",
        instructions="Read the ticket and decide its severity.",
        evaluates=(Criterion(name="severity",
                             question="How severe is the ticket?",
                             possible_values=("low", "medium", "high")),),
        marks_done=("classify",),
    ),
    WorkflowStepDefinition(
        id=2, name="EscalateIfHigh",
        gate=Gate(checks=(GateCheck(variable="severity", value="high"),)),
        instructions="Write a one-paragraph escalation note to ops.",
        routes=(Route(criteria_name="severity", value="low", goto_step=4),
                Route(criteria_name="severity", value="medium", goto_step=3)),
        tool_uses=(ToolUse(tool_name="rule-checker", note="verify policy"),),
        subagents=("critic",),          # invoked at this step
        marks_done=("escalate",),
    ),
]
```

Only `id` and `name` are required, so you can stub steps first and fill in
detail later. `preamble` / `postamble` on the AgentDefinition wrap the
rendered block. `examples/60_workflow_agent/` exercises every field.

## 2. Understand what compiles: STEP 0 and todo_mode

The compiler renders the steps as a `## MANDATORY WORKFLOW` section. With
`todo_mode="strict"` (the default) it prepends a **STEP 0: Create Task List**
block that instructs the agent to create one todo per step (from `todo_name` +
`todo_description`), emits a per-step "mark done" line, and closes with a
FINAL CHECKLIST that verifies all todos completed.

- `strict` — STEP 0 plus per-step completion marks. Use when audit trails
  matter (production orchestrators).
- `lazy` — STEP 0 once, no per-step marks. The agent focuses on work, not
  bookkeeping.
- `none` — no todo machinery at all. For one-shot agents.

Primaries use the runtime's `todowrite`/`todoread` tools; subagents don't have
them, so the compiler switches their todo blocks to the bundled
`subagent_todo.py` file-based tracker automatically. Setting
`workspace=".agent_workspace/{name}"` additionally emits a STEP 0a block that
initializes an isolated sandbox via `workspace_io.py` (and the security policy
then forbids file creation through bash).

## 3. Build an orchestrator tree

Subagents are referenced twice: as `AgentHeader`s on the parent's `subagents`
field, and as their own `TemplateSlot`s so they compile alongside the parent.
The slot named `"primary"` compiles in primary mode; every other slot becomes
a subagent.

```python
from open_agent_compiler import (
    AgentDefinition, AgentHeader, AgentRegistry, CompilationConfig,
    ModelParameters, TemplateSlot, TemplateTree,
)

orchestrator = AgentDefinition(
    header=AgentHeader(agent_id="orchestrator", name="orchestrator",
                       description="Routes input through summarizer + critic."),
    usage_explanation_long="Summarise then critique via delegation.",
    usage_explanation_short="summarise + critique orchestrator",
    subagents=[
        AgentHeader(agent_id="summarizer", name="summarizer",
                    description="Compress text into one paragraph.",
                    mode="subagent"),
        AgentHeader(agent_id="critic", name="critic",
                    description="Argue against the user's claim.",
                    mode="subagent"),
    ],
    system_prompt="Delegate via the Task tool; never summarise inline. ...",
)

reg = AgentRegistry()
orch_id = reg.register_agent("orchestrator", orchestrator,
    ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.2))
sum_id = reg.register_agent("summarizer", summarizer_defn, ...)
crit_id = reg.register_agent("critic", critic_defn, ...)

reg.register_template(TemplateTree(name="tpl", slots=[
    TemplateSlot(name="primary", default_agent_id=orch_id),
    TemplateSlot(name="summarizer", default_agent_id=sum_id),
    TemplateSlot(name="critic", default_agent_id=crit_id),
]))
reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
```

The compiled orchestrator gains an "## Available Subagents" section with the
exact Task-tool call for each child (`subagent_type: "summarizer"`), plus
`permission: task: allow` in its frontmatter. Each agent in the tree can run
on a different model — the compiler writes each subagent's model into its own
frontmatter, so mixed-provider trees work unchanged
(`examples/40_subagents/`). Subagents cannot delegate further: fan-out is
one level deep. If a workflow step names a subagent, that agent must *also*
appear in `defn.subagents`, or the security policy will forbid the invocation.

## 4. Know the permissions model

`tool_permissions=AgentToolPermissions(read=..., write=..., edit=..., mcp=...)`
compiles into **both** the enforcement config (the frontmatter `permission:` /
`tool:` blocks, default-deny with explicit allows for each declared bash
command, skill, and Task target) **and** a SECURITY POLICY prompt section
listing ALLOWED and FORBIDDEN actions — enforcement and agent awareness stay
in sync from one source of truth. Per-server MCP allowlists come from
`mcp_servers=[MCPServerDefinition(name="slack", allowed_tools=[...])]`.

## 5. Dual-compile workers with `also_compile_as_primary`

A subagent slot compiles to `mode: subagent` and cannot be invoked via
`opencode run --agent <name>` — opencode falls back to the default agent.
That breaks direct dispatch and improvement-loop evaluation. Set the flag on
the slot:

```python
TemplateSlot(name="transcript-scorer", default_agent_id=scorer_id,
             also_compile_as_primary=True)
```

The compiler emits BOTH `transcript-scorer.md` (subagent, for Task delegation)
AND `transcript-scorer-primary.md` (primary mode, callable directly via
`opencode run --agent transcript-scorer-primary` or from another primary via
`opencode_manager.py`). Use it on every worker you want to evaluate or
dispatch to in isolation.

## 6. Spawn patterns: primary-to-primary dispatch

Setting `mode="primary"` on a subagent reference switches the composition
from Task-tool delegation to bash dispatch through the bundled
`opencode_manager.py` (auto-copied into `build/scripts/`, with the matching
bash allowlist). The worker keeps a clean primary identity — its own
subagents, its own session — and long-running work doesn't chew up the
parent's context window (`examples/50_primary_dispatch/`).

The typed equivalent is `SpawnAgentTool`, a ScriptTool wrapping the same
dispatcher, returning a `TaskHandle`:

```python
from open_agent_compiler import SpawnAgentInput, SpawnAgentTool

out = SpawnAgentTool().execute(SpawnAgentInput(
    agent_name="number-cruncher-primary",   # the -primary twin
    prompt="What is 6 * 7?",
    context={"user_id": "alice"},           # → OAC_CTX_USER_ID env var
    spawn_async=True,
))
print(out.task.run_id, out.task.status, out.task.poll_url)
```

`spawn_async=False` blocks until done (best for short workers; `timeout_s`
guards it). `spawn_async=True` fires and forgets, returning a running
`TaskHandle` with a `poll_url` (`/runs/{run_id}/await`) that the scaffolded
FastAPI service drains later. The target must be primary-mode — combine with
`also_compile_as_primary` so a worker is reachable both ways. See
`examples/31_spawn_agent/`.

## Related pages

- [Agent model concepts](../concepts/agent-model.md)
- [Execution tiers](../concepts/execution-tiers.md)
- [Authoring tools](tools.md)
- [Testing](testing.md)
- [CLI reference](../reference/cli.md)
