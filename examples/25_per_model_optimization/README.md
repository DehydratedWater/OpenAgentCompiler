# 25 per-model optimization

Same weak baseline optimised **separately for each model class** using
`run_per_class_loops` (Phase 6.8). Different model_classes get
different winning prompts, snapshotted under
`improved/<component>/<class>/<hash>.json`.

## Setup

- **SplitProfile** with two classes:
  - `fast` → `zai-coding-plan/glm-4.5-air`
  - `analytical` → `zai-coding-plan/glm-5.1`
- **Optimiser** (the LLM that proposes mutations): `glm-5.1`,
  regardless of which class is being optimised. The same mutator
  rewrites the prompt with class-specific guidance; the evaluator
  scores it on the per-class target model.
- **Mutators**: Identity (control) + prompt-prefix (deterministic) +
  LLMPromptRewriter (glm-5.1 with guidance about tuning per class).
- **Evaluator**: reads `version.definition['model_class']`, invokes
  opencode with the class's target model, scores response length +
  trade-off mentions.

## Run

```bash
uv run python examples/25_per_model_optimization/improve_run.py
```

Expect 6-12 opencode calls per class × 2 classes ≈ 15-25 invocations.
~3-5 minutes on z.ai max plan.

## Output

```
improved/multi-model-explainer/
  fast/
    <hash>.json          ← winners optimised for glm-4.5-air
    LATEST.json
  analytical/
    <hash>.json          ← winners optimised for glm-5.1
    LATEST.json
```

## Promote per class

```bash
# Use the fast-optimised prompt when running against glm-4.5-air
uv run oac promote improved/multi-model-explainer/fast/LATEST.json

# Or the analytical-optimised prompt for glm-5.1
uv run oac promote improved/multi-model-explainer/analytical/LATEST.json
```

## What's exercised

- Phase 6.8 `run_per_class_loops` — one IterativeLoop per class entry.
- `SplitProfile` driving per-class compilation.
- An evaluator that picks its target model from the candidate's
  declared model_class.
- Class-aware mutation guidance — the LLM rewriter is told to tune for
  the class the candidate will run under.
- Per-class snapshot organisation under `improved/<component>/<class>/`.

## What this proves

The framework actually evolves DIFFERENT prompts for different models.
The "best" prompt for glm-4.5-air may differ from the "best" prompt for
glm-5.1; the loop discovers each independently rather than picking one
compromise prompt that runs everywhere.
