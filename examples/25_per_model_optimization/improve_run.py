"""Run run_per_class_loops — one IterativeLoop per SplitProfile class.

The evaluator reads the class binding from each candidate's
definition['model_class'] and invokes opencode against the matching
fully-qualified model. Snapshots land under improved/<component>/<class>/
so the user can promote the per-class winner separately.

The OPTIMISER (the LLM that rewrites prompts via LLMPromptRewriter) is
glm-5.1 regardless of which target class is being optimised. That
mirrors the typical setup: one strong model proposes mutations; each
class evaluates the mutations against its own target model.

Usage:
    uv run python examples/25_per_model_optimization/improve_run.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))  # priority: this example's local 'agents'
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "examples" / "_shared"))

from agents import (  # noqa: E402
    CLASS_MODEL,
    CRITERION,
    SPLIT_PROFILE,
    TEST_PROMPTS,
    registry,
)
from opencode_runtime import (  # noqa: E402
    OpencodeMutatorClient,
    run_candidate_prompt,
)

from open_agent_compiler.improvement import (  # noqa: E402
    ComponentVersion,
    IdentityMutator,
    LLMPromptRewriter,
    MutationContext,
    PromptPrefixMutator,
    run_per_class_loops,
)


OPTIMISER_MODEL = "zai-coding-plan/glm-5.1"


def evaluator(version: ComponentVersion) -> dict[str, float]:
    """Invoke the candidate against the model bound to its model_class."""
    model_class = version.definition.get("model_class", "fast")
    target_model = CLASS_MODEL.get(model_class)
    if not target_model:
        print(f"  [evaluator] unknown class {model_class!r}; treating as fast")
        target_model = CLASS_MODEL["fast"]

    system_prompt = version.definition.get("system_prompt", "")
    if not system_prompt:
        return {
            "score_floor:by_name:response-min-length": 0.0,
            "score_floor:by_name:response-mentions-tradeoffs": 0.0,
        }

    responses = []
    for prompt in TEST_PROMPTS:
        try:
            r = run_candidate_prompt(
                system_prompt, prompt, model=target_model, timeout_s=120,
            )
        except Exception as exc:
            print(f"  [evaluator] failure prompt={prompt[:40]!r}: {exc}")
            r = ""
        responses.append(r)

    avg_len = sum(len(r) for r in responses) / max(1, len(responses))
    length_score = min(1.0, avg_len / 400.0)
    keywords = ("trade-off", "tradeoff", "however", "while", "but ", "depend")
    hit_rate = sum(
        any(k in r.lower() for k in keywords) for r in responses
    ) / max(1, len(responses))

    metrics = {
        "score_floor:by_name:response-min-length": length_score,
        "score_floor:by_name:response-mentions-tradeoffs": hit_rate,
    }
    print(
        f"  [evaluator] class={model_class:11s} {version.author!r:32s}"
        f" hash={version.content_hash[:8]}…"
        f" len={length_score:.2f} trade={hit_rate:.2f}"
    )
    return metrics


def baseline_version() -> ComponentVersion:
    reg = registry()
    resolved = reg.resolve_config("prod")
    variant = resolved["primary"]
    return ComponentVersion.of(
        component_id="multi-model-explainer",
        kind="agent",
        definition=json.loads(variant.agent_definition.model_dump_json()),
        author="human",
    )


def main() -> None:
    baseline = baseline_version()
    print(f"baseline prompt: {baseline.definition['system_prompt']!r}")
    print(f"split classes: {list(SPLIT_PROFILE.class_map)}")
    print(f"class → model: {CLASS_MODEL}")
    print(f"optimiser (LLM mutator): {OPTIMISER_MODEL}")

    optimiser = OpencodeMutatorClient(model=OPTIMISER_MODEL)
    mutators = [
        IdentityMutator(),
        PromptPrefixMutator(
            "When the user asks for an explanation, write 2-4 sentences"
            " that name the trade-offs explicitly."
        ),
        LLMPromptRewriter(
            guidance=(
                "Rewrite this AGENT system prompt so it produces fuller"
                " answers (2-4 sentences that mention trade-offs). Tune"
                " for the model class the candidate will run under — small"
                " models prefer tight directive prompts; large analytical"
                " models prefer richer context and explicit framing."
                " Keep the rewrite under 300 chars."
            ),
        ),
    ]
    ctx = MutationContext(llm=optimiser)

    print(f"\n=== running per-class loops; "
          f"{len(SPLIT_PROFILE.class_map)} classes ===\n")

    output = HERE / "improved"
    results = run_per_class_loops(
        baseline=baseline,
        mutators=mutators,
        criterion=CRITERION,
        evaluator=evaluator,
        split_profile=SPLIT_PROFILE,
        max_rounds=2,
        frontier_size=2,
        output=output,
        mutation_context=ctx,  # forward the LLM client to each per-class loop
    )

    print("\n=== done; per-class winners ===\n")
    for class_name, result in results.items():
        winners = result.loop_result.winners
        print(f"  class={class_name} preset={result.preset_id}")
        for w in winners:
            avg_score = sum(w.metrics.values()) / max(1, len(w.metrics))
            print(
                f"    WINNER {w.author!r:32s} hash={w.content_hash[:8]}…"
                f" avg={avg_score:.3f}"
            )
            print(f"      prompt: {w.definition['system_prompt'][:120]!r}…")
    print(f"\nsnapshots under {output}/")


if __name__ == "__main__":
    main()
