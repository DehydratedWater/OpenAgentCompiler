"""run_per_target_loops: one IterativeLoop per (harness × model_class) target."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.mutators import IdentityMutator, PromptPrefixMutator
from open_agent_compiler.improvement.target_loop import (
    OptimizationTarget,
    run_per_target_loops,
    targets_from_split_profile,
)
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.model.core.split_profile import SplitProfile


def _baseline() -> ComponentVersion:
    return ComponentVersion.of(
        component_id="orch", kind="agent",
        definition={"name": "orch", "system_prompt": "be helpful"},
    )


def _criterion() -> OptimisationCriterion:
    return OptimisationCriterion(
        name="passes", criteria=(Criterion(kind="pass_rate", target=1.0, hard=True),),
    )


def _split() -> SplitProfile:
    fast = ModelPreset(
        name="fast-preset", provider="vllm", model_id="qwen35-fast",
        sampling=SamplingDefaults(temperature=0.0),
    )
    deep = ModelPreset(
        name="deep-preset", provider="anthropic", model_id="sonnet",
        sampling=SamplingDefaults(temperature=0.7),
    )
    return SplitProfile(
        name="split", postfix="-split",
        preset=deep, class_map={"fast": fast, "analytical": deep},
    )


# ---- OptimizationTarget -----------------------------------------------


def test_target_key_with_and_without_class() -> None:
    assert OptimizationTarget(harness="pi", model_class="fast").key == "pi+fast"
    assert OptimizationTarget(harness="interactive").key == "interactive"


def test_targets_from_split_profile_cross_product() -> None:
    targets = targets_from_split_profile(["opencode", "pi"], _split())
    keys = [t.key for t in targets]
    assert keys == [
        "opencode+fast", "opencode+analytical",
        "pi+fast", "pi+analytical",
    ]
    # preset bookkeeping carried through
    by_key = {t.key: t for t in targets}
    assert by_key["pi+fast"].preset_id == "fast-preset"
    assert by_key["opencode+analytical"].preset_id == "deep-preset"


# ---- run_per_target_loops ---------------------------------------------


def test_per_target_loops_run_once_per_target() -> None:
    targets = targets_from_split_profile(["opencode", "pi"], _split())
    out = run_per_target_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator(), PromptPrefixMutator("CRITICAL: ")],
        criterion=_criterion(),
        targets=targets,
        evaluator_factory=lambda t: (lambda v: {"pass_rate": 1.0}),
        max_rounds=1,
        frontier_size=2,
    )
    assert set(out.keys()) == {
        "opencode+fast", "opencode+analytical", "pi+fast", "pi+analytical",
    }
    for result in out.values():
        assert result.loop_result.winners


def test_per_target_baselines_stamp_class_and_target_meta() -> None:
    targets = [OptimizationTarget(harness="pi", model_class="fast", preset_id="fast-preset")]
    out = run_per_target_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator()],
        criterion=_criterion(),
        targets=targets,
        evaluator_factory=lambda t: (lambda v: {"pass_rate": 1.0}),
        max_rounds=1,
    )
    for v in out["pi+fast"].loop_result.winners:
        assert v.definition.get("model_class") == "fast"
        meta = v.definition.get("_oac_meta") or {}
        assert meta.get("target") == "pi+fast"
        assert meta.get("harness") == "pi"
        assert meta.get("preset_id") == "fast-preset"


def test_per_target_loops_write_snapshots_under_target_key(tmp_path: Path) -> None:
    output = tmp_path / "improved"
    targets = targets_from_split_profile(["opencode", "pi"], _split())
    out = run_per_target_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator(), PromptPrefixMutator("X: ")],
        criterion=_criterion(),
        targets=targets,
        evaluator_factory=lambda t: (lambda v: {"pass_rate": 1.0}),
        max_rounds=1,
        output=output,
    )
    for key in out:
        target_dir = output / "orch" / key
        snaps = list(target_dir.glob("*.json"))
        assert snaps, f"expected snapshots under {target_dir}"
        assert (target_dir / "LATEST.json").exists()


def test_per_target_evaluator_factory_receives_each_target() -> None:
    seen: list[str] = []

    def factory(target: OptimizationTarget):
        seen.append(target.key)
        return lambda v: {"pass_rate": 1.0}

    targets = [
        OptimizationTarget(harness="opencode", model_class="fast"),
        OptimizationTarget(harness="interactive"),
    ]
    run_per_target_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator()],
        criterion=_criterion(),
        targets=targets,
        evaluator_factory=factory,
        max_rounds=1,
    )
    assert seen == ["opencode+fast", "interactive"]


def test_per_target_loops_forward_mutation_context() -> None:
    from open_agent_compiler.improvement.mutators import LLMPromptRewriter, MutationContext
    from open_agent_compiler.improvement.mutators.llm import _StubLLM

    llm = _StubLLM(response="REWRITTEN")
    ctx = MutationContext(llm=llm)
    run_per_target_loops(
        baseline=_baseline(),
        mutators=[LLMPromptRewriter()],
        criterion=_criterion(),
        targets=[
            OptimizationTarget(harness="opencode", model_class="fast"),
            OptimizationTarget(harness="pi", model_class="fast"),
        ],
        evaluator_factory=lambda t: (lambda v: {"pass_rate": 1.0}),
        max_rounds=1,
        mutation_context=ctx,
    )
    assert len(llm.calls) >= 2
