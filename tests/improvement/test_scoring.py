"""Criterion → scoring logic."""

from __future__ import annotations

from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.scoring import (
    aggregate_score,
    continuous_score,
    hard_pass,
    metric_key,
    passes,
)


def test_metric_key_for_any_scope_is_bare_kind() -> None:
    assert metric_key(Criterion(kind="pass_rate", target=1.0)) == "pass_rate"


def test_metric_key_for_by_evaluator_includes_scope_value() -> None:
    c = Criterion(
        kind="score_floor", target=0.8,
        scope="by_evaluator", scope_value="llm_judge",
    )
    assert metric_key(c) == "score_floor:by_evaluator:llm_judge"


def test_metric_key_for_named_scope_includes_scope() -> None:
    c = Criterion(kind="pass_rate", target=1.0, scope="capability_tests")
    assert metric_key(c) == "pass_rate:capability_tests"


# ---- passes (hard check) -----------------------------------------------


def test_passes_higher_is_better_kinds() -> None:
    c = Criterion(kind="pass_rate", target=0.9)
    assert passes(c, {"pass_rate": 0.95})
    assert not passes(c, {"pass_rate": 0.5})


def test_passes_lower_is_better_kinds() -> None:
    c = Criterion(kind="latency_p95", target=2.0)
    assert passes(c, {"latency_p95": 1.5})
    assert not passes(c, {"latency_p95": 3.0})


def test_passes_missing_metric_is_soft_pass() -> None:
    c = Criterion(kind="pass_rate", target=1.0)
    assert passes(c, {})


# ---- continuous_score --------------------------------------------------


def test_continuous_score_higher_is_better_saturates_at_1() -> None:
    c = Criterion(kind="pass_rate", target=0.5)
    assert continuous_score(c, {"pass_rate": 1.0}) == 1.0
    assert continuous_score(c, {"pass_rate": 0.25}) == 0.5
    assert continuous_score(c, {"pass_rate": 0.0}) == 0.0


def test_continuous_score_lower_is_better_penalises_overshoot() -> None:
    c = Criterion(kind="latency_p95", target=2.0)
    assert continuous_score(c, {"latency_p95": 1.0}) == 1.0
    # 50% over budget → score 0.5
    assert continuous_score(c, {"latency_p95": 3.0}) == 0.5
    assert continuous_score(c, {"latency_p95": 4.0}) == 0.0


def test_continuous_score_missing_metric_neutral() -> None:
    c = Criterion(kind="pass_rate", target=1.0)
    assert continuous_score(c, {}) == 0.5


def test_continuous_score_zero_target_higher_is_better() -> None:
    c = Criterion(kind="pass_rate", target=0.0)
    assert continuous_score(c, {"pass_rate": 0.0}) == 1.0


# ---- aggregate -------------------------------------------------------


def _oc(*criteria, aggregation="all") -> OptimisationCriterion:
    return OptimisationCriterion(
        name="oc", aggregation=aggregation, criteria=tuple(criteria),
    )


def test_all_aggregation_requires_every_soft_pass() -> None:
    oc = _oc(
        Criterion(kind="pass_rate", target=1.0),
        Criterion(kind="latency_p95", target=2.0),
    )
    assert aggregate_score(oc, {"pass_rate": 1.0, "latency_p95": 1.0}) == 1.0
    # One fails → mean drops to 0.5
    assert aggregate_score(oc, {"pass_rate": 1.0, "latency_p95": 3.0}) == 0.5


def test_weighted_aggregation_weights_criteria() -> None:
    oc = _oc(
        Criterion(kind="pass_rate", target=1.0, weight=1.0),
        Criterion(kind="score_floor", target=1.0, weight=3.0),
        aggregation="weighted",
    )
    # pass_rate=0.5 → score 0.5; score_floor=1.0 → score 1.0
    # weighted = (1*0.5 + 3*1.0) / 4 = 0.875
    score = aggregate_score(oc, {"pass_rate": 0.5, "score_floor": 1.0})
    assert abs(score - 0.875) < 1e-6


def test_hard_pass_ignores_soft_failures() -> None:
    oc = _oc(
        Criterion(kind="pass_rate", target=1.0, hard=True),
        Criterion(kind="latency_p95", target=2.0),  # soft
    )
    # Hard passes; soft fails → hard_pass returns True
    assert hard_pass(oc, {"pass_rate": 1.0, "latency_p95": 5.0})
    # Hard fails → False
    assert not hard_pass(oc, {"pass_rate": 0.5, "latency_p95": 1.0})


def test_zero_weight_aggregation_returns_zero() -> None:
    oc = OptimisationCriterion(
        name="oc", aggregation="weighted",
        criteria=(
            Criterion(kind="pass_rate", target=1.0, weight=0.0),
        ),
    )
    assert aggregate_score(oc, {"pass_rate": 1.0}) == 0.0


# ---- tool_failure_rate criterion (Phase 13) -------------------------


def test_tool_failure_rate_passes_when_at_or_below_target() -> None:
    """Lower-is-better: 0.02 failure rate passes a target of 0.05."""
    c = Criterion(kind="tool_failure_rate", target=0.05)
    assert passes(c, {"tool_failure_rate": 0.02})
    assert passes(c, {"tool_failure_rate": 0.05})
    assert not passes(c, {"tool_failure_rate": 0.10})


def test_tool_failure_rate_continuous_score_is_1_at_or_below_target() -> None:
    c = Criterion(kind="tool_failure_rate", target=0.05)
    assert continuous_score(c, {"tool_failure_rate": 0.0}) == 1.0
    assert continuous_score(c, {"tool_failure_rate": 0.05}) == 1.0


def test_tool_failure_rate_continuous_score_degrades_proportionally() -> None:
    """Overshoot of 100% reduces score to 0; partial overshoot is linear."""
    import pytest
    c = Criterion(kind="tool_failure_rate", target=0.05)
    # 0.075 = 1.5x target → 0.5x overshoot → score 0.5.
    assert continuous_score(c, {"tool_failure_rate": 0.075}) == pytest.approx(0.5)
    assert continuous_score(c, {"tool_failure_rate": 0.10}) == 0.0


def test_tool_failure_rate_aggregates_with_pass_rate() -> None:
    """Composite of pass_rate (higher better) + tool_failure_rate works."""
    oc = OptimisationCriterion(
        name="oc", aggregation="weighted",
        criteria=(
            Criterion(kind="pass_rate", target=1.0, weight=1.0),
            Criterion(kind="tool_failure_rate", target=0.05, weight=1.0),
        ),
    )
    score = aggregate_score(
        oc, {"pass_rate": 1.0, "tool_failure_rate": 0.0},
    )
    assert score == 1.0


# --- blended criterion: mean + soft p25 floor (stochastic-agent promotion) ---

def test_score_mean_and_quantile_are_higher_is_better():
    from open_agent_compiler.improvement.criteria import Criterion
    from open_agent_compiler.improvement.scoring import passes, continuous_score
    for kind in ("score_mean", "score_quantile"):
        c = Criterion(name=kind, kind=kind, target=0.75)
        assert passes(c, {kind: 0.84}) is True
        assert passes(c, {kind: 0.50}) is False
        assert continuous_score(c, {kind: 0.75}) == 1.0
        assert round(continuous_score(c, {kind: 0.375}), 2) == 0.5


def test_blend_promotes_good_agent_with_one_flaky_probe():
    """mean 0.84, p25 ~0.6 (one 0 among many high) → promotable."""
    from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
    from open_agent_compiler.improvement.scoring import aggregate_score, hard_pass
    blend = OptimisationCriterion(
        name="b", aggregation="weighted",
        criteria=(
            Criterion(name="mean", kind="score_mean", target=1.0, weight=1.0),
            Criterion(name="floor", kind="score_quantile", target=0.5,
                      weight=0.0, hard=True),
        ),
    )
    good = {"score_mean": 0.84, "score_quantile": 0.6, "score_floor": 0.0}
    assert aggregate_score(blend, good) >= 0.75   # winner_score ~ mean
    assert hard_pass(blend, good) is True         # p25 guard clears


def test_blend_blocks_broadly_broken_agent():
    """Many low probes → low p25 → hard guard fails even if mean scrapes by."""
    from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
    from open_agent_compiler.improvement.scoring import hard_pass
    blend = OptimisationCriterion(
        name="b", aggregation="weighted",
        criteria=(
            Criterion(name="mean", kind="score_mean", target=1.0, weight=1.0),
            Criterion(name="floor", kind="score_quantile", target=0.5,
                      weight=0.0, hard=True),
        ),
    )
    broken = {"score_mean": 0.55, "score_quantile": 0.1, "score_floor": 0.0}
    assert hard_pass(blend, broken) is False
