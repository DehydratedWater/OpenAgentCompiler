"""Run the iterative improvement loop on weak-explainer using glm-5.1.

Wires together:
- Phase 6 IterativeLoop
- LLMPromptRewriter mutator
- OpencodeMutatorClient (z.ai/glm-5.1 as the optimiser)
- A real evaluator that invokes each candidate against TEST_PROMPTS via
  opencode and scores the response.

Usage:
    uv run python examples/20_optimization_run/improve_run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "examples" / "_shared"))

from agents import CRITERION, TEST_PROMPTS, registry  # noqa: E402
from opencode_runtime import (  # noqa: E402
    OpencodeMutatorClient,
    run_candidate_prompt,
)

from open_agent_compiler.improvement import (  # noqa: E402
    ComponentVersion,
    IdentityMutator,
    IterativeLoop,
    LLMPromptRewriter,
    MutationContext,
    PromptPrefixMutator,
    write_round_winners,
)


# z.ai/glm-4.5-air for the target candidates, z.ai/glm-5.1 for the optimiser.
TARGET_MODEL = "zai-coding-plan/glm-4.5-air"
OPTIMISER_MODEL = "zai-coding-plan/glm-5.1"


def evaluator(version: ComponentVersion) -> dict[str, float]:
    """Run each TEST_PROMPT through the candidate and score the responses."""
    system_prompt = version.definition.get("system_prompt", "")
    if not system_prompt:
        return {"score_floor": 0.0, "score_floor:by_name:response-min-length": 0.0}

    responses = []
    for prompt in TEST_PROMPTS:
        try:
            r = run_candidate_prompt(system_prompt, prompt, model=TARGET_MODEL)
        except Exception as exc:
            print(f"  [evaluator] failure for prompt {prompt[:40]!r}: {exc}")
            r = ""
        responses.append(r)

    # Deterministic scoring: long responses score better.
    avg_len = sum(len(r) for r in responses) / max(1, len(responses))
    length_score = min(1.0, avg_len / 400.0)  # 400+ chars = full credit

    # Trade-off mention: did the model actually engage with the trade-off?
    keywords = ("trade-off", "tradeoff", "however", "while", "but ", "depend")
    hit_rate = sum(
        any(k in r.lower() for k in keywords) for r in responses
    ) / max(1, len(responses))

    metrics = {
        "score_floor:by_name:response-min-length": length_score,
        "score_floor:by_name:response-mentions-tradeoffs": hit_rate,
    }
    print(
        f"  [evaluator] {version.author!r:32s} hash={version.content_hash[:8]}…"
        f" len={length_score:.2f} tradeoffs={hit_rate:.2f}"
    )
    return metrics


def baseline_version() -> ComponentVersion:
    """Pull the weak-explainer out of the registry as the loop's seed."""
    reg = registry()
    resolved = reg.resolve_config("prod")
    variant = resolved["primary"]
    import json
    return ComponentVersion.of(
        component_id="weak-explainer",
        kind="agent",
        definition=json.loads(variant.agent_definition.model_dump_json()),
        author="human",
    )


def main() -> None:
    baseline = baseline_version()
    print(f"baseline prompt: {baseline.definition['system_prompt']!r}")

    optimiser = OpencodeMutatorClient(model=OPTIMISER_MODEL)
    mutators = [
        # Control — confirms the loop doesn't regress.
        IdentityMutator(),
        # Quick deterministic nudge to anchor the frontier.
        PromptPrefixMutator(
            "When the user asks for an explanation, write 2-4 sentences"
            " that name the trade-offs explicitly."
        ),
        # The real workhorse — glm-5.1 rewrites the prompt.
        LLMPromptRewriter(
            guidance=(
                "Rewrite this AGENT system prompt so it produces fuller"
                " answers. The current prompt makes the agent give one-sentence"
                " replies; the target is 2-4 sentences that mention"
                " trade-offs explicitly. Keep the rewrite under 200 chars."
            ),
        ),
    ]

    ctx = MutationContext(llm=optimiser)

    loop = IterativeLoop(
        baseline=baseline,
        mutators=mutators,
        criterion=CRITERION,
        evaluator=evaluator,
        max_rounds=2,
        frontier_size=2,
        mutation_context=ctx,
    )

    print(f"\n=== running {loop.max_rounds} rounds; "
          f"optimiser={OPTIMISER_MODEL} target={TARGET_MODEL} ===\n")
    result = loop.run()

    print(f"\n=== loop done; rounds={len(result.rounds)} "
          f"winners={len(result.winners)} archive={len(result.archive)} ===\n")
    for w in result.winners:
        print(
            f"  WINNER {w.author!r:32s} hash={w.content_hash[:8]}… "
            f"metrics={w.metrics}"
        )
        print(f"    prompt: {w.definition['system_prompt'][:120]!r}…")

    out = HERE / "improved"
    snapshot_paths = write_round_winners(
        result.winners, out, run_label=CRITERION.name,
    )
    print(f"\nwrote {len(snapshot_paths)} snapshot(s) under {out}")
    for p in snapshot_paths:
        print(f"  - {p.relative_to(HERE)}")


if __name__ == "__main__":
    main()
