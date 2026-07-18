# 27 composable-improvements — self-evolving parts you can mix and match

This example demonstrates the framework's most important compositional
guarantee:

> Every piece of a composable agent tree (the agent prompt, each skill,
> each tool) can point at its own auto-improved twin. If a promoted
> snapshot exists for that piece, it loads automatically. If none has
> been promoted yet, the baseline ships unchanged. The user keeps
> writing one composable definition; the framework swaps in whichever
> independently auto-optimised pieces have been promoted.

## The agent under construction

`agents.py` defines a single `time-explainer` agent with:

- An agent system prompt.
- A `time-awareness` skill with workflow steps + rules.
- A `time-tool` ToolDefinition embedded inside that skill.

Each piece carries its own `component_id` (the agent's `agent_id`, the
skill's `name`, the tool's `header.name`). Each can be improved
independently via a separate `oac improve` loop targeting its own
evaluator + criterion. Each promotes into a slot under
`.oac/promoted/<component_id>.json`.

## How the registry pulls them in

```python
agent_id = reg.register_with_improvements(
    "time-explainer",
    _baseline_agent(),
    ModelParameters(...),
    project_root=HERE,
    model_class="default",
)
```

`register_with_improvements` walks the AgentDefinition tree (agent
itself + every skill + every tool inside every skill + every
`extra_tools`) and merges promoted snapshots onto each piece using
`apply_promoted_to_tree`. The walk:

1. Looks for `.oac/promoted/time-explainer__<model_class>.json`; falls
   back to `.oac/promoted/time-explainer.json`; falls back to leaving
   the agent baseline unchanged.
2. Same fallback chain for each skill (keyed by skill name).
3. Same fallback chain for each tool (keyed by tool name).

You get partial promotions for free: if only the tool's been improved
and promoted, only the tool merges. Run `oac improve` again later for
the skill — promote it — next compile picks that up too without
touching the tool or the agent prompt's plumbing.

## Running the example

Seed three independent example promotions (stand-ins for what real
`oac improve` runs would produce):

```bash
uv run python examples/27_composable_improvements/seed_improvements.py
```

You'll see:

```
Promoted three independent improvements:
  agent prompt → .oac/promoted/time-explainer.json
  tool        → .oac/promoted/time-tool.json
  skill       → .oac/promoted/time-awareness.json
```

Then compile:

```bash
uv run python examples/27_composable_improvements/build_agents.py
```

Open `build/.opencode/agents/primary.md` and you'll see all three
improvements applied: the improved system prompt, the improved
`time-tool` description + rules, and the improved skill section body.

## Demonstrating partial promotions

Delete any subset of `.oac/promoted/*.json` and recompile. Whichever
pieces you leave promoted still merge; whichever you delete fall back
to the baseline shipped in `agents.py`. There's no required ordering
and no coupling between which pieces have been improved.

## Per-class promotions

Pass `--class fast` to `oac promote`:

```bash
oac promote improved/time-tool/<hash>.json --class fast
```

…writes to `.oac/promoted/time-tool__fast.json`. The
`register_with_improvements(..., model_class="fast")` call picks
that up first, falling back to the default
`.oac/promoted/time-tool.json` when no class-specific promotion
exists. That makes it safe to have one agent run multiple variants
in the same compile (e.g. one for the fast model class, one for the
local Qwen class) without each variant needing its own registry
factory.

## What was new in the framework for this example

- `find_promoted_snapshot(component_id, project_root, model_class=None)`
  — per-class > default > None resolution.
- `apply_promoted_to_tool` / `apply_promoted_to_skill` — per-kind
  field-merge helpers.
- `apply_promoted_to_tree(agent_def, project_root, model_class=None)`
  — walks the agent + skills + skills' tools + extra_tools and merges
  every promotion in one call.
- `AgentRegistry.register_with_improvements(...)` — one-line
  registration that auto-applies promoted improvements before
  registering.
- `oac promote --class <name>` — writes to the per-class slot.
