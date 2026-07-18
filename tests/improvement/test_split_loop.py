"""run_per_class_loops: one IterativeLoop per SplitProfile class."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.mutators import IdentityMutator, PromptPrefixMutator
from open_agent_compiler.improvement.split_loop import run_per_class_loops
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
        name="fast", provider="vllm", model_id="qwen35-fast",
        sampling=SamplingDefaults(temperature=0.0),
    )
    deep = ModelPreset(
        name="deep", provider="anthropic", model_id="sonnet",
        sampling=SamplingDefaults(temperature=0.7),
    )
    return SplitProfile(
        name="split", postfix="-split",
        preset=deep, class_map={"fast": fast, "analytical": deep},
    )


def test_per_class_loops_run_once_per_class_entry() -> None:
    out = run_per_class_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator(), PromptPrefixMutator("CRITICAL: ")],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        split_profile=_split(),
        max_rounds=1,
        frontier_size=2,
    )
    assert set(out.keys()) == {"fast", "analytical"}
    assert out["fast"].preset_id == "fast"
    assert out["analytical"].preset_id == "deep"
    assert out["fast"].loop_result.winners
    assert out["analytical"].loop_result.winners


def test_per_class_baselines_carry_class_into_definition() -> None:
    out = run_per_class_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator()],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        split_profile=_split(),
        max_rounds=1,
    )
    for class_name, result in out.items():
        # Each winner's definition records its model_class binding.
        for v in result.loop_result.winners:
            assert v.definition.get("model_class") == class_name


def test_per_class_loops_write_snapshots_when_output_set(tmp_path: Path) -> None:
    output = tmp_path / "improved"
    out = run_per_class_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator(), PromptPrefixMutator("X: ")],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        split_profile=_split(),
        max_rounds=1,
        output=output,
    )
    # Snapshots organised by class.
    for class_name in out:
        class_dir = output / "orch" / class_name
        snaps = list(class_dir.glob("*.json"))
        assert snaps, f"expected snapshots under {class_dir}"
        assert (class_dir / "LATEST.json").exists()


def test_per_class_loops_no_output_does_not_write(tmp_path: Path) -> None:
    output = tmp_path / "improved"
    run_per_class_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator()],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        split_profile=_split(),
        max_rounds=1,
        output=None,
    )
    assert not output.exists()


def test_per_class_loops_evaluator_sees_class_aware_versions() -> None:
    seen_classes: set[str] = set()

    def evaluator(v):
        seen_classes.add(v.definition.get("model_class", ""))
        return {"pass_rate": 1.0}

    run_per_class_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator()],
        criterion=_criterion(),
        evaluator=evaluator,
        split_profile=_split(),
        max_rounds=1,
    )
    assert seen_classes == {"fast", "analytical"}


def test_per_class_loops_forwards_mutation_context_to_each_loop() -> None:
    """LLM-backed mutators need ctx.llm — silently no-op without it."""
    from open_agent_compiler.improvement.mutators import LLMPromptRewriter, MutationContext
    from open_agent_compiler.improvement.mutators.llm import _StubLLM

    llm = _StubLLM(response="REWRITTEN")
    ctx = MutationContext(llm=llm)

    run_per_class_loops(
        baseline=_baseline(),
        mutators=[LLMPromptRewriter()],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        split_profile=_split(),
        max_rounds=1,
        mutation_context=ctx,
    )
    # The LLM should have been called at least once per class.
    assert len(llm.calls) >= 2


def test_per_class_loops_without_mutation_context_skips_llm_mutators() -> None:
    """Regression: ensure the no-context path doesn't crash, just no-ops."""
    from open_agent_compiler.improvement.mutators import LLMPromptRewriter

    run_per_class_loops(
        baseline=_baseline(),
        mutators=[LLMPromptRewriter()],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        split_profile=_split(),
        max_rounds=1,
        # mutation_context omitted on purpose
    )
