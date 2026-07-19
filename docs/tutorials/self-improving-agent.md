# Tutorial: a self-improving agent

*Mini-project for: the improvement loop — criterion, mutators,
evaluator, `oac promote`, and automatic reload.*

## The problem

Your agent's prompt is mediocre, and hand-tuning it is guesswork: you
tweak a sentence, eyeball two responses, and hope. The framework turns
this into a measured loop — define what "better" means as a scored
criterion, let mutators propose prompt candidates, evaluate every
candidate against real test prompts, and promote the measured winner so
the *next compile automatically ships it*.

## What you'll build

A deliberately weak explainer agent (it answers in one terse sentence
when users need real explanations), plus an improvement loop that
rewrites its prompt with an LLM, scores each candidate, and closes the
cycle: **benchmark → improve → promote → reload → re-benchmark**.

Prerequisites: [installation](../getting-started/installation.md) and
the `opencode` CLI with a configured provider (the loop shells out to
`opencode run` for evaluation and mutation). This tutorial is adapted
from `examples/20_optimization_run` and `examples/26_promote_and_reload`;
copy `examples/_shared/opencode_runtime.py` (the `OpencodeMutatorClient`
+ `run_candidate_prompt` subprocess helpers) next to your project.

## Step 1 — a weak baseline that auto-applies promotions

`agents.py`. The one non-obvious line is `apply_promoted_to_agent`: it
checks `.oac/promoted/<component_id>.json` and, if a promotion exists,
merges the improved fields onto the baseline. Fresh project → no-op;
after `oac promote` → every compile, test, and run uses the winner.

```python
from __future__ import annotations

from pathlib import Path

from open_agent_compiler import (
    AgentDefinition, AgentHeader, AgentRegistry, CompilationConfig,
    ModelParameters, TemplateSlot, TemplateTree,
)
from open_agent_compiler.improvement import apply_promoted_to_agent

HERE = Path(__file__).resolve().parent


def _baseline_agent() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="weak-explainer", name="weak-explainer",
            description="Explains software concepts in a single sentence.",
        ),
        usage_explanation_long="Reads a software question and replies briefly.",
        usage_explanation_short="terse software explainer",
        # Deliberately weak: one-line answers when users need paragraphs.
        system_prompt=(
            "You are a quick assistant. Answer the user in one sentence."
            " Be brief."
        ),
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()
    agent = apply_promoted_to_agent(
        _baseline_agent(), component_id="weak-explainer", project_root=HERE,
    )
    agent_id = reg.register_agent(
        "weak-explainer", agent,
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.3),
    )
    reg.register_template(TemplateTree(
        name="tpl", slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
    ))
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
    return reg
```

## Step 2 — say what "better" means

An `OptimisationCriterion` aggregates named sub-criteria. The
`Criterion.for_named(...)` form scopes each one to a metric key the
evaluator will emit (`score_floor:by_name:<name>`):

```python
from open_agent_compiler import OptimisationCriterion
from open_agent_compiler.improvement import Criterion

CRITERION = OptimisationCriterion(
    name="full-explanations",
    aggregation="weighted",
    criteria=(
        Criterion.for_named("response-min-length", "score_floor",
                            target=1.0, weight=2.0),
        Criterion.for_named("response-mentions-tradeoffs", "score_floor",
                            target=1.0, weight=1.0),
    ),
)

TEST_PROMPTS = [
    "Explain the trade-off between consistency and availability in distributed systems.",
    "What is the difference between a process and a thread, and when would I pick each?",
]
```

## Step 3 — the evaluator and the loop

`improve_run.py`. Three mutators run per round: an identity control, a
deterministic prefix nudge, and an LLM rewriter (a stronger model
proposes new prompts). The evaluator runs every candidate against the
test prompts through opencode and scores the responses:

```python
import json
from pathlib import Path

from agents import CRITERION, TEST_PROMPTS, registry
from opencode_runtime import OpencodeMutatorClient, run_candidate_prompt

from open_agent_compiler.improvement import (
    ComponentVersion, IdentityMutator, IterativeLoop, LLMPromptRewriter,
    MutationContext, PromptPrefixMutator, write_round_winners,
)

TARGET_MODEL = "zai-coding-plan/glm-4.5-air"     # runs the candidates
OPTIMISER_MODEL = "zai-coding-plan/glm-5.1"      # proposes rewrites


def evaluator(version: ComponentVersion) -> dict[str, float]:
    system_prompt = version.definition.get("system_prompt", "")
    responses = [
        run_candidate_prompt(system_prompt, p, model=TARGET_MODEL)
        for p in TEST_PROMPTS
    ]
    avg_len = sum(len(r) for r in responses) / max(1, len(responses))
    keywords = ("trade-off", "tradeoff", "however", "while", "but ", "depend")
    hit_rate = sum(
        any(k in r.lower() for k in keywords) for r in responses
    ) / max(1, len(responses))
    length_score = min(1.0, avg_len / 400.0)
    print(f"  [evaluator] {version.author!r:24s} len={length_score:.2f}"
          f" tradeoffs={hit_rate:.2f}")
    return {
        "score_floor:by_name:response-min-length": length_score,
        "score_floor:by_name:response-mentions-tradeoffs": hit_rate,
    }


def main() -> None:
    reg = registry()
    variant = reg.resolve_config("prod")["primary"]
    baseline = ComponentVersion.of(
        component_id="weak-explainer", kind="agent",
        definition=json.loads(variant.agent_definition.model_dump_json()),
        author="human",
    )
    loop = IterativeLoop(
        baseline=baseline,
        mutators=[
            IdentityMutator(),
            PromptPrefixMutator(
                "When the user asks for an explanation, write 2-4 sentences"
                " that name the trade-offs explicitly."
            ),
            LLMPromptRewriter(guidance=(
                "Rewrite this AGENT system prompt so it produces fuller"
                " 2-4 sentence answers that mention trade-offs explicitly."
                " Keep the rewrite under 200 chars."
            )),
        ],
        criterion=CRITERION,
        evaluator=evaluator,
        max_rounds=2,
        frontier_size=2,
        mutation_context=MutationContext(llm=OpencodeMutatorClient(model=OPTIMISER_MODEL)),
    )
    result = loop.run()
    write_round_winners(result.winners, Path("improved"), run_label=CRITERION.name)


if __name__ == "__main__":
    main()
```

## Run it

```bash
uv run python improve_run.py
```

Watch the per-candidate scores climb as mutated prompts beat the
baseline:

```
  [evaluator] 'human'                 len=0.37 tradeoffs=1.00
  [evaluator] 'prompt-prefix'         len=0.81 tradeoffs=1.00
  [evaluator] 'llm-prompt-rewriter'   len=1.00 tradeoffs=1.00
...
  WINNER 'llm-prompt-rewriter' hash=3fa1c2d9… metrics={...: 1.00, ...: 1.00}
```

Winners are snapshotted under `improved/weak-explainer/<hash>.json`
plus a `LATEST.json` pointer. Now promote and reload:

```bash
uv run oac promote improved/weak-explainer/LATEST.json --project .
# oac promote: weak-explainer → .oac/promoted/weak-explainer.json
#   (pick up on next `python build_agents.py` run)

uv run python -c "from agents import _baseline_agent, HERE; \
from open_agent_compiler.improvement import apply_promoted_to_agent; \
print(apply_promoted_to_agent(_baseline_agent(), 'weak-explainer', project_root=HERE).system_prompt)"
```

The printed prompt is the *improved* one — the registry from Step 1
now ships it in every compile with zero further changes. For the fully
scripted before/after cycle (benchmark → improve → promote →
re-benchmark, with delta bars), run
`examples/26_promote_and_reload/run_cycle.py` from the repo.

There is also a CLI form once you have a criteria YAML and an
importable evaluator:
`oac improve <module:factory> --target primary --config prod
--criteria criteria.yaml --mutators identity,llm-prompt-rewriter
--evaluator mypkg.evals:run --output improved/` — see the
[improvement-loop guide](../guides/improvement-loop.md).

## Why it works

The loop is ordinary search with your quality bar as the objective:
mutators generate prompt candidates, the evaluator measures each one on
real model runs, and the criterion collapses the metrics into a
comparable score so only measured improvements survive a round. The
promotion file is the crucial last mile — because the registry merges
it at build time, "the agent got better" is a committed, reproducible
state of the project rather than a snapshot rotting in a folder.

## Going further

- [Improvement loop guide](../guides/improvement-loop.md) — criteria
  YAML, bundled mutators, per-class loops.
- `examples/25_per_model_optimization` — one loop per model class, so
  each model gets its own winning prompt.
- [Testing guide](../guides/testing.md) — turn `oac test` suites into
  evaluators.
- [Philosophy](../concepts/philosophy.md) — why everything ships
  autoloop-testable.
