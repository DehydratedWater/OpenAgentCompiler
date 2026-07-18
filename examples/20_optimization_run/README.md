# 20 optimization run

End-to-end exercise of Phase 6's autoresearch loop. A deliberately-weak
agent is improved by an LLM rewriter using **z.ai glm-5.1** as the
optimiser, with **z.ai glm-4.5-air** as the target the candidates run
on.

## Setup

The weak baseline tells the target model "answer in one sentence, be
brief", which is the wrong shape for the questions in `TEST_PROMPTS`.
The criterion has two soft sub-criteria:
- **response-min-length** — average response is at least ~400 chars (full credit)
- **response-mentions-tradeoffs** — the response contains trade-off
  keywords ("trade-off" / "however" / "depend" / …)

Three mutators run each round:
- `IdentityMutator` — control (so the baseline's score is visible).
- `PromptPrefixMutator(…)` — a deterministic nudge that prepends an
  explicit "2-4 sentences, name the trade-offs" instruction.
- `LLMPromptRewriter(guidance=…)` — calls glm-5.1 via
  `OpencodeMutatorClient` to rewrite the system prompt with the
  failure context.

The evaluator invokes each candidate as an ephemeral opencode agent
(temp dir + `.opencode/agents/candidate.md` + `opencode run`), scores
the responses, and returns metrics the loop aggregates against the
criterion.

## Run

```bash
uv run python examples/20_optimization_run/improve_run.py
```

Expect ~5-10 opencode subprocess calls (3 mutators × 2 rounds × 2
test prompts × evaluator overhead). z.ai max coding plan has no
hard rate limit so the loop completes in a couple of minutes.

Output:
- `examples/20_optimization_run/improved/weak-explainer/<hash>.json`
  per round winner + `LATEST.json`.

## Promote a winner

```bash
uv run oac promote \
    examples/20_optimization_run/improved/weak-explainer/LATEST.json \
    --project examples/20_optimization_run
```

Drops the improved prompt at
`examples/20_optimization_run/.oac/promoted/weak-explainer.json` for
the next compile to pick up.

## What's exercised

- Phase 6 IterativeLoop end-to-end with three mutator kinds.
- LLMPromptRewriter + a real LLMMutatorClient
  (`OpencodeMutatorClient` shells out to `opencode run --model …`).
- Real evaluation that invokes each candidate against test prompts via
  opencode subprocess.
- Composite hashing + green-index skipping (re-run the script — round
  2 reuses round-1 results when hashes match).
- Snapshot emission + promote workflow.
