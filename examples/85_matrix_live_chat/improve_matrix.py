"""Adapt the summarizer to every (harness × model) target — plus the
interactive tier — in one per-target autoloop run.

Offline by default so the mechanics are visible without credentials:

- Mutators propose three prompt styles (baseline, "Be concise.",
  "Think step by step.").
- Each compiled target's evaluator models that harness/model's real
  preference (a fast model on pi wants terse prompts; a smart model on
  opencode benefits from reasoning room) — so DIFFERENT prompts win on
  different targets, which is the whole point of the matrix.
- The "interactive" target evaluates candidates by actually running
  them through `run_interactive` with a scripted ChatClient, scored by
  an llm_judge probe (StubJudge offline — swap AnthropicJudge for a
  real LLM-as-judge, same wiring).
- Every round/candidate/winner is recorded in the SQLite run store;
  file output is one finalized snapshot per target. Winners are
  promoted into per-target slots so `build_matrix.py` and
  `live_chat.py` pick them up.

Browse afterwards:  uv run oac versions list summarizer --project examples/85_matrix_live_chat

To run this against LIVE harnesses instead: build the matrix first,
then have `evaluator_factory` return an evaluator that shells out via
`get_runner(target.harness, build_dir)` and scores `final_text()` with
your judge — see docs/guides/optimization-targets.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

from open_agent_compiler.improvement import (  # noqa: E402
    Criterion,
    IdentityMutator,
    OptimisationCriterion,
    OptimizationTarget,
    Probe,
    PromptPrefixMutator,
    Snapshot,
    build_interactive_evaluator,
    open_store,
    promote,
    run_per_target_loops,
)
from open_agent_compiler.improvement.version import ComponentVersion  # noqa: E402
from open_agent_compiler.interactive.runner import ChatResponse  # noqa: E402
from open_agent_compiler.interactive.spec import InteractiveAgentSpec  # noqa: E402
from open_agent_compiler.model.core.model_preset import (  # noqa: E402
    ModelPreset,
    SamplingDefaults,
)
from open_agent_compiler.model.core.test_model import LLMJudgeEvaluator  # noqa: E402
from open_agent_compiler.testing.judges.stub import StubJudge  # noqa: E402

COMPONENT = "summarizer"

TARGETS = [
    OptimizationTarget(harness="opencode", model_class="fast"),
    OptimizationTarget(harness="opencode", model_class="analytical"),
    OptimizationTarget(harness="pi", model_class="fast"),
    OptimizationTarget(harness="pi", model_class="analytical"),
    OptimizationTarget(harness="interactive"),
]

# What each target's harness/model actually rewards (offline stand-in
# for shelling out to the real harness + LLM judge).
_PREFERS = {
    "opencode+fast": "Be concise.",
    "opencode+analytical": "Think step by step.",
    "pi+fast": "Be concise.",
    "pi+analytical": "Be concise.",   # pi's terse rendering favors short prompts
}


def _compiled_evaluator(target: OptimizationTarget):
    prefer = _PREFERS[target.key]

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        prompt = str(version.definition.get("system_prompt", ""))
        return {"pass_rate": 1.0 if prompt.startswith(prefer) else 0.0}

    return evaluator


class _EchoClient:
    """Scripted live-tier model: answers with the rendered system prompt so
    the judge can see which candidate actually reached it."""

    def complete(self, *, messages, tools, model, **params):
        return ChatResponse(content=messages[0]["content"])


def _interactive_evaluator():
    def spec_factory(defn: dict) -> InteractiveAgentSpec:
        return InteractiveAgentSpec(
            agent_id=COMPONENT,
            model=ModelPreset(name="live", provider="local-vllm",
                              model_id="local-model",
                              sampling=SamplingDefaults(temperature=0.2)),
            system_prompt=str(defn.get("system_prompt", "")),
        )

    # A StubJudge subclass stands in for a real LLM judge: it approves
    # candidates whose rendered prompt asks for step-by-step reasoning
    # (what the live chat tier wants). AnthropicJudge drops in with zero
    # other wiring changes.
    class _ReasoningAwareJudge(StubJudge):
        def judge(self, criteria, target, *, model=None):
            ok = "Think step by step." in str(target)
            return {"pass": ok, "score": 1.0 if ok else 0.2,
                    "reasoning": "stub: looked for reasoning request"}

    return build_interactive_evaluator(
        [Probe(
            probe_id="reasoning-style",
            payload="summarize: the sky is blue",
            evaluators=(LLMJudgeEvaluator(
                criteria="asks for step-by-step reasoning",
                pass_threshold=0.5,
            ),),
        )],
        spec_factory,
        client=_EchoClient(),
        judge=_ReasoningAwareJudge(),
    )


def evaluator_factory(target: OptimizationTarget):
    if target.harness == "interactive":
        return _interactive_evaluator()
    return _compiled_evaluator(target)


def main() -> None:
    store = open_store(project_root=HERE)
    baseline = ComponentVersion.of(
        component_id=COMPONENT, kind="agent",
        definition={"name": COMPONENT,
                    "system_prompt": "Summarize the input in one paragraph."},
    )
    results = run_per_target_loops(
        baseline=baseline,
        mutators=[
            IdentityMutator(),
            PromptPrefixMutator("Be concise. "),
            PromptPrefixMutator("Think step by step. "),
        ],
        criterion=OptimisationCriterion(
            name="target-fit",
            criteria=(Criterion(kind="pass_rate", target=1.0, hard=False),),
        ),
        targets=TARGETS,
        evaluator_factory=evaluator_factory,
        max_rounds=1,
        frontier_size=1,
        output=HERE / "improved",
        store=store,
    )

    print(f"{'target':<22}{'winning prompt prefix'}")
    for key, res in results.items():
        best = res.loop_result.best(metric="pass_rate")
        prompt = str(best.definition["system_prompt"])
        print(f"{key:<22}{prompt[:48]!r}")

    # Promote each target's finalized snapshot into its own slot.
    for key in results:
        latest = HERE / "improved" / COMPONENT / key / "LATEST.json"
        snap = Snapshot.model_validate_json(latest.read_text())
        if snap.version.metrics.get("pass_rate", 0.0) < 1.0:
            print(f"  (skipping promote for {key}: no candidate fit)")
            continue
        promote(latest, HERE, target=key, force=True, store=store)
        print(f"  promoted {key} → .oac/promoted/{COMPONENT}__{key}.json")

    print("\n✓ Same component, five targets, five independently-tuned winners.")
    print("  Re-run build_matrix.py — each harness build now embeds its own"
          " winner;\n  live_chat.py picks up the 'interactive' one.")


if __name__ == "__main__":
    main()
