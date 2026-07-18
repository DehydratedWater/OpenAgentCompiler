# 26 promote-and-reload — closing the loop

Demonstrates the **actual usage loop** the user flagged was missing
from `20_optimization_run`: after `oac improve` + `oac promote`, the
next compile picks up the improved prompt automatically.

Without this loop closed, snapshots would just sit in `improved/`
unused.

## The key pattern (in `agents.py`)

```python
from open_agent_compiler.improvement import apply_promoted_to_agent

def registry():
    baseline = AgentDefinition(... system_prompt="weak baseline" ...)
    # Auto-merge any promoted improvements. No-op on fresh projects.
    agent = apply_promoted_to_agent(
        baseline,
        component_id="reload-explainer",
        project_root=HERE,
    )
    reg.register_agent("…", agent, …)
    …
```

`apply_promoted_to_agent` looks for
`<project_root>/.oac/promoted/<component_id>.json`. If present, it
merges `system_prompt` / `preamble` / `postamble` / `todo_mode` /
`model_class` onto the baseline. Structural state (subagents, tools,
permissions) is preserved.

## Run

```bash
uv run python examples/26_promote_and_reload/run_cycle.py
```

This script orchestrates the full cycle:

1. Clear any prior promotion → benchmark the weak baseline
2. Run improvement loop with glm-5.1 as optimiser
3. Promote the winner into `.oac/promoted/`
4. Re-benchmark — the SAME registry now uses the improved prompt
5. Print before/after metric bars with delta

## Expected output

```
============================================================
STEP 1: Benchmark baseline (weak prompt)
============================================================
baseline response (148 chars): "Consistency means…"
baseline metrics: {'length': 0.37, 'tradeoffs': 1.00}

============================================================
STEP 2: Run improvement loop
============================================================
… loop runs …
round 0: ███████··· 0.580
round 1: ██████████ 1.000  (+0.42 from llm-prompt-rewriter)

============================================================
STEP 3: Promote the winner into .oac/promoted/
============================================================
promoted to: .oac/promoted/reload-explainer.json

============================================================
STEP 4: Re-benchmark with the promoted prompt
============================================================
promoted response (412 chars): "The trade-off between…"
promoted metrics: {'length': 1.00, 'tradeoffs': 1.00}

============================================================
DELTA
============================================================
length:      before ███████·············  0.37
             after  ████████████████████  1.00  Δ=+0.63
tradeoffs:   before ████████████████████  1.00
             after  ████████████████████  1.00  Δ=+0.00
```

## What's exercised

- `apply_promoted_to_agent` in a real registry factory.
- `load_promoted_definition` for explicit inspection of the loaded
  promotion.
- `promote(snapshot, project_root)` API + the
  `.oac/promoted/<safe_id>.json` convention.
- End-to-end: same code path runs the baseline AND the improved
  version — just the promoted file changes.
- ASCII delta visualisation so improvements are visible at a glance.

## Take this back to your own project

The pattern in `agents.py` is the entire integration. Drop it in your
registry factory and the autoresearch loop becomes a tool you can run
periodically — `oac improve` finds a better prompt, `oac promote`
saves it, your next build picks it up.
