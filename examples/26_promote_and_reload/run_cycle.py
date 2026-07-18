"""End-to-end: compile → benchmark → improve → promote → reload → re-benchmark.

The point of this example is to PROVE the improved agent actually gets
used after promotion — not just sits in a snapshot file. Output prints
the before/after metrics so the improvement is visible.

Usage:
    uv run python examples/26_promote_and_reload/run_cycle.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))  # priority: this example's local 'agents'
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "examples" / "_shared"))

from agents import TEST_PROMPT, _baseline_agent, registry  # noqa: E402
from opencode_runtime import (  # noqa: E402
    OpencodeMutatorClient,
    run_candidate_prompt,
)

from open_agent_compiler.compiler.script import CompileScript  # noqa: E402
from open_agent_compiler.improvement import (  # noqa: E402
    ComponentVersion,
    Criterion,
    IdentityMutator,
    IterativeLoop,
    LLMPromptRewriter,
    MutationContext,
    OptimisationCriterion,
    PromptPrefixMutator,
    load_promoted_definition,
    promote,
    render_round_progression,
    write_round_winners,
)


TARGET_MODEL = "zai-coding-plan/glm-4.5-air"
OPTIMISER_MODEL = "zai-coding-plan/glm-5.1"

CRITERION = OptimisationCriterion(
    name="cycle-criterion",
    aggregation="weighted",
    criteria=(
        Criterion.for_named("length", "score_floor", 1.0, weight=2.0),
        Criterion.for_named("tradeoffs", "score_floor", 1.0, weight=1.0),
    ),
)


def _score_response(text: str) -> dict[str, float]:
    """Same scoring as 20_optimization_run for direct comparability."""
    length_score = min(1.0, len(text) / 400.0)
    keywords = ("trade-off", "tradeoff", "however", "while", "but ", "depend")
    has_tradeoff = 1.0 if any(k in text.lower() for k in keywords) else 0.0
    return {
        "score_floor:by_name:length": length_score,
        "score_floor:by_name:tradeoffs": has_tradeoff,
    }


def benchmark_current_registry() -> dict:
    """Compile the registry as-is and run TEST_PROMPT against the primary agent.

    Returns the response + scored metrics so callers can compare runs
    before and after promotion.
    """
    build_dir = HERE / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)

    CompileScript(
        target=build_dir, factory=registry, config="prod",
        clean=True, verbose=False,
    ).run()

    # opencode subprocess needs PWD env set for project discovery.
    import os
    env = {**os.environ, "PWD": str(build_dir.resolve())}
    result = subprocess.run(
        ["opencode", "run", "--format", "json", "--agent", "primary", TEST_PROMPT],
        cwd=str(build_dir), env=env,
        capture_output=True, text=True, timeout=120,
    )
    from opencode_runtime import _parse_opencode_json_stream
    response = _parse_opencode_json_stream(result.stdout)
    metrics = _score_response(response)
    return {"response": response, "metrics": metrics}


def run_improvement_loop() -> ComponentVersion | None:
    """Run a short improvement loop on the baseline; return the top winner."""
    baseline = ComponentVersion.of(
        component_id="reload-explainer",
        kind="agent",
        definition=json.loads(_baseline_agent().model_dump_json()),
        author="human",
    )

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        system_prompt = version.definition.get("system_prompt", "")
        if not system_prompt:
            return _score_response("")
        try:
            response = run_candidate_prompt(
                system_prompt, TEST_PROMPT, model=TARGET_MODEL, timeout_s=90,
            )
        except Exception as exc:
            print(f"  [evaluator] failure: {exc}")
            response = ""
        metrics = _score_response(response)
        print(
            f"  [evaluator] {version.author!r:32s}"
            f" len={metrics['score_floor:by_name:length']:.2f}"
            f" trade={metrics['score_floor:by_name:tradeoffs']:.2f}"
        )
        return metrics

    optimiser = OpencodeMutatorClient(model=OPTIMISER_MODEL)
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
                " 2-4 sentence answers that mention trade-offs. Keep it"
                " under 300 chars."
            )),
        ],
        criterion=CRITERION,
        evaluator=evaluator,
        max_rounds=2,
        frontier_size=2,
        mutation_context=MutationContext(llm=optimiser),
    )
    print("\n=== improvement loop ===")
    result = loop.run()
    print(render_round_progression(result, CRITERION))

    snap_dir = HERE / "improved"
    if snap_dir.exists():
        shutil.rmtree(snap_dir)
    write_round_winners(result.winners, snap_dir, run_label="cycle")
    return result.winners[0] if result.winners else None


def main() -> None:
    # 1. Clear any prior promotion so we benchmark the real baseline.
    promoted_dir = HERE / ".oac" / "promoted"
    if promoted_dir.exists():
        shutil.rmtree(promoted_dir)

    print("=" * 60)
    print("STEP 1: Benchmark baseline (weak prompt)")
    print("=" * 60)
    baseline_run = benchmark_current_registry()
    print(f"baseline response ({len(baseline_run['response'])} chars):")
    print(f"  {baseline_run['response'][:200]}…")
    print(f"baseline metrics: {baseline_run['metrics']}")

    print()
    print("=" * 60)
    print("STEP 2: Run improvement loop")
    print("=" * 60)
    winner = run_improvement_loop()
    if winner is None:
        print("loop produced no winner; aborting")
        return

    snap_path = HERE / "improved" / "reload-explainer" / f"{winner.content_hash[:12]}.json"
    print(f"\ntop winner snapshot: {snap_path.relative_to(HERE)}")
    print(f"new prompt: {winner.definition['system_prompt']!r}")

    print()
    print("=" * 60)
    print("STEP 3: Promote the winner into .oac/promoted/")
    print("=" * 60)
    dest = promote(snap_path, HERE)
    print(f"promoted to: {dest.relative_to(HERE)}")

    # Verify the loader sees it.
    loaded = load_promoted_definition("reload-explainer", project_root=HERE)
    assert loaded is not None
    print("load_promoted_definition() returns the new prompt:")
    print(f"  {loaded['system_prompt'][:160]!r}…")

    print()
    print("=" * 60)
    print("STEP 4: Re-benchmark with the promoted prompt")
    print("=" * 60)
    promoted_run = benchmark_current_registry()
    print(f"promoted response ({len(promoted_run['response'])} chars):")
    print(f"  {promoted_run['response'][:200]}…")
    print(f"promoted metrics: {promoted_run['metrics']}")

    print()
    print("=" * 60)
    print("DELTA")
    print("=" * 60)
    for key in baseline_run["metrics"]:
        before = baseline_run["metrics"][key]
        after = promoted_run["metrics"][key]
        delta = after - before
        bar_before = "█" * int(before * 20) + "·" * (20 - int(before * 20))
        bar_after = "█" * int(after * 20) + "·" * (20 - int(after * 20))
        print(f"  {key:50s}")
        print(f"    before: {bar_before} {before:.2f}")
        print(f"    after:  {bar_after} {after:.2f}  Δ={delta:+.2f}")


if __name__ == "__main__":
    main()
