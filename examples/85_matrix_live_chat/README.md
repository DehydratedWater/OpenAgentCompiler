# 85 matrix-live-chat — one definition, every harness, every model

The capstone flow: **define an agent tree once (with benchmarks), then
let autoloops adapt it to each harness and model it runs on** — and use
all the adapted variants at the same time from one realtime chat agent.

Three connected agents (orchestrator → summarizer + critic) become:

```
                       ┌───────────── one Python definition ─────────────┐
                       │  agents.py  (apply_promoted_to_tree(target=…))  │
                       └───────┬─────────────────┬─────────────┬─────────┘
     compiled workers          │                 │             │   realtime tier
  build_opencode/  primary.md, primary-smart.md  │             │
  build_pi/        primary.md, primary-smart.md ─┘             │
                                                   live_chat.py (run_interactive)
                                                   └─ spawn_worker → any of the 4
```

## 1. Compile the matrix

```bash
uv run python examples/85_matrix_live_chat/build_matrix.py
```

Two dialects × two `VariantSpec`s = four runnable workers per slot.
Compiles are recorded in the run store (`.oac/improvement.db`).

## 2. Adapt per target with autoloops

```bash
uv run python examples/85_matrix_live_chat/improve_matrix.py
```

`run_per_target_loops` runs one loop per `OptimizationTarget` — the four
compiled cells **plus `interactive`** — and different prompts win on
different targets (terse for pi/fast models, step-by-step for the
analytical opencode cell and the chat tier, judged by an `llm_judge`
probe through the interactive evaluator). Winners are promoted into
per-target slots:

```
.oac/promoted/summarizer__opencode+fast.json
.oac/promoted/summarizer__pi+analytical.json
.oac/promoted/summarizer__interactive.json
...
```

Intermediate history (every round/candidate/score) lives in the SQLite
store, not files. Browse and manage it:

```bash
uv run oac versions list summarizer --project examples/85_matrix_live_chat
uv run oac versions rollback summarizer --target pi+fast --project examples/85_matrix_live_chat
```

## 3. Re-compile — each build embeds its own winner

```bash
uv run python examples/85_matrix_live_chat/build_matrix.py
grep -l "Be concise" examples/85_matrix_live_chat/build_pi/.pi/agents/*.md
```

Promotion resolution is `target → model_class → default`, so untuned
targets degrade gracefully to shared winners or the Python baseline.

## 4. One live chat over the whole matrix

```bash
uv run python examples/85_matrix_live_chat/live_chat.py          # offline demo
uv run python examples/85_matrix_live_chat/live_chat.py --live   # real provider + harnesses
```

The realtime orchestrator uses the **interactive-tuned** prompt (the
same `apply_promoted_to_tree`, `target="interactive"`) and holds one
`spawn_worker` tool that dispatches through `get_runner(harness, dir)` —
`pi smart`, `opencode fast`, any cell, all from the same conversation.

## Going live

The offline evaluators stand in for the real loop legs; swap them 1:1:

- compiled targets → `get_runner(target.harness, build_dir)` +
  score `final_text()` with `AnthropicJudge` (LLM-as-judge),
- interactive target → drop the scripted client from
  `build_interactive_evaluator` so it hits your live provider,
- scale out → wrap the per-leaf loops and the orchestrator's
  `build_branch_loop` (routing quality) into `run_fleet` units.

## See also

- [Optimization targets guide](../../docs/guides/optimization-targets.md) — the full story this example demonstrates
- `examples/25_per_model_optimization/` — live per-model loops (opencode, real judge)
- `examples/26_promote_and_reload/` — the promote → recompile contract
