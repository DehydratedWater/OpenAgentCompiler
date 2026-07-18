"""IterativeLoop: end-to-end mutate → evaluate → score → promote."""

from __future__ import annotations

from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.loop import IterativeLoop
from open_agent_compiler.improvement.mutators import (
    IdentityMutator,
    PromptPrefixMutator,
    PromptSuffixMutator,
)
from open_agent_compiler.improvement.version import ComponentVersion


def _agent(prompt: str = "be helpful") -> dict:
    return {"name": "orch", "system_prompt": prompt}


def _criterion() -> OptimisationCriterion:
    return OptimisationCriterion(
        name="be-good",
        criteria=(Criterion(kind="pass_rate", target=1.0, hard=True),),
    )


def test_baseline_only_run_returns_baseline_as_winner() -> None:
    base = ComponentVersion.of("orch", "agent", _agent())
    loop = IterativeLoop(
        baseline=base,
        mutators=[IdentityMutator()],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 0.5},
        max_rounds=1,
        frontier_size=2,
    )
    out = loop.run()
    # Identity produces a sibling candidate; both end up in winners list.
    names = {v.author for v in out.winners}
    assert "identity" in names or "human" in names


def test_evaluator_metrics_propagated_to_registered_versions() -> None:
    base = ComponentVersion.of("orch", "agent", _agent("v1"))
    def evaluator(v):
        # Mutated versions (those carrying the prefix) score higher.
        if "BETTER:" in v.definition.get("system_prompt", ""):
            return {"pass_rate": 1.0}
        return {"pass_rate": 0.7}
    loop = IterativeLoop(
        baseline=base,
        mutators=[PromptPrefixMutator("BETTER:")],
        criterion=_criterion(),
        evaluator=evaluator,
        max_rounds=1,
    )
    out = loop.run()
    versions = loop.registry.history("orch")
    assert all("pass_rate" in v.metrics for v in versions)
    mutated = [v for v in versions if "BETTER:" in v.definition.get("system_prompt", "")]
    assert mutated and mutated[0].metrics["pass_rate"] == 1.0


def test_hard_criterion_filters_out_failing_candidates() -> None:
    base = ComponentVersion.of("orch", "agent", _agent())
    def evaluator(v):
        # Mutated versions fail the hard check.
        if v.author == "prompt-prefix:BAD:":
            return {"pass_rate": 0.0}
        return {"pass_rate": 1.0}
    loop = IterativeLoop(
        baseline=base,
        mutators=[PromptPrefixMutator("BAD:")],
        criterion=_criterion(),
        evaluator=evaluator,
        max_rounds=1,
    )
    out = loop.run()
    # The bad candidate is in `candidates` but not in `survivors`.
    round0 = out.rounds[0]
    assert any("BAD:" in c.definition.get("system_prompt", "") for c in round0.candidates)
    assert not any("BAD:" in c.definition.get("system_prompt", "") for c in round0.survivors)


def test_loop_stops_early_when_no_new_candidates() -> None:
    # All mutators return None on the first round → loop exits.
    base = ComponentVersion.of("orch", "agent", {"name": "x"})  # not an agent prompt
    class _NeverApplies(IdentityMutator):
        def mutate(self, v, ctx):
            return None
    loop = IterativeLoop(
        baseline=base,
        mutators=[_NeverApplies()],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        max_rounds=10,
    )
    out = loop.run()
    assert len(out.rounds) == 1
    assert out.rounds[0].candidates == []


def test_multiple_rounds_grow_lineage() -> None:
    base = ComponentVersion.of("orch", "agent", _agent("v0"))
    # Two mutators: prefix + suffix → 2 candidates per parent per round
    loop = IterativeLoop(
        baseline=base,
        mutators=[
            PromptPrefixMutator("PRE:"),
            PromptSuffixMutator(":POST"),
        ],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        max_rounds=3,
        frontier_size=2,
    )
    out = loop.run()
    assert len(out.rounds) >= 1
    # All children parent_hash linked back to baseline OR to a survivor.
    for round_out in out.rounds:
        for c in round_out.candidates:
            assert c.parent_hash is not None
            assert loop.registry.get(c.parent_hash) is not None


def test_winners_sorted_by_aggregate_score() -> None:
    base = ComponentVersion.of("orch", "agent", _agent("v0"))
    scores = {"PRE:": 0.9, ":POST": 0.7}

    def evaluator(v):
        for marker, val in scores.items():
            if marker in v.definition.get("system_prompt", ""):
                return {"pass_rate": val}
        return {"pass_rate": 1.0}  # baseline

    loop = IterativeLoop(
        baseline=base,
        mutators=[PromptPrefixMutator("PRE:"), PromptSuffixMutator(":POST")],
        criterion=_criterion(),
        evaluator=evaluator,
        max_rounds=1,
        frontier_size=3,
    )
    out = loop.run()
    score_keys = [
        v.metrics.get("pass_rate") for v in out.winners
    ]
    # Should be sorted descending.
    assert score_keys == sorted(score_keys, reverse=True)


def test_archive_contains_non_winners() -> None:
    base = ComponentVersion.of("orch", "agent", _agent())
    loop = IterativeLoop(
        baseline=base,
        mutators=[PromptPrefixMutator("X:"), PromptSuffixMutator(":Y")],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        max_rounds=1,
        frontier_size=1,  # tight frontier so we get archives
    )
    out = loop.run()
    # At least 2 candidates produced; 1 winner; archive should be non-empty.
    total = len(out.winners) + len(out.archive)
    assert total == len(loop.registry.history("orch"))
    assert len(out.winners) == 1
