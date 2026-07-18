"""Criterion → score functions.

Each Criterion translates to (a) a hard pass/fail check and (b) a
continuous 0..1 score for weighted aggregation. Scoring is pure: takes
a metrics dict + a criterion, returns numbers. The loop combines them.
"""

from __future__ import annotations

from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion


def metric_key(criterion: Criterion) -> str:
    """Resolve the dict key in metrics that this criterion looks at.

    Convention:
    - 'any' scope → bare kind ('pass_rate' / 'score_floor' / …)
    - typed scopes → 'kind:scope:scope_value'
    """
    if criterion.scope == "any":
        return criterion.kind
    if criterion.scope in ("by_evaluator", "by_name"):
        return f"{criterion.kind}:{criterion.scope}:{criterion.scope_value}"
    # capability_tests / tool_tests / agent_tests
    return f"{criterion.kind}:{criterion.scope}"


def passes(criterion: Criterion, metrics: dict[str, float]) -> bool:
    """Hard pass/fail. Missing metric → True (soft-skip)."""
    key = metric_key(criterion)
    if key not in metrics:
        return True
    val = metrics[key]
    if criterion.kind in (
        "pass_rate", "score_floor", "score_mean", "score_quantile",
    ):
        return val >= criterion.target
    # latency_p95 / cost_ceiling / determinism / tool_failure_rate are
    # 'lower is better' — the metric must be at or below the target.
    return val <= criterion.target


def continuous_score(
    criterion: Criterion, metrics: dict[str, float],
) -> float:
    """0..1 score for weighted aggregation. Missing metric → 0.5 (neutral)."""
    key = metric_key(criterion)
    if key not in metrics:
        return 0.5
    val = metrics[key]
    target = criterion.target
    if criterion.kind in (
        "pass_rate", "score_floor", "score_mean", "score_quantile",
    ):
        if target <= 0:
            return 1.0
        return min(1.0, val / target)
    if criterion.kind in (
        "latency_p95", "cost_ceiling", "determinism", "tool_failure_rate",
    ):
        if target <= 0:
            # Avoid divide-by-zero; treat 0-target as 'must be exactly 0'.
            return 1.0 if val == 0 else 0.0
        if val <= target:
            return 1.0
        overshoot = (val - target) / target
        return max(0.0, 1.0 - overshoot)
    return 0.0


def hard_pass(
    optimisation: OptimisationCriterion, metrics: dict[str, float],
) -> bool:
    """Every `hard=True` criterion must pass; soft criteria ignored here."""
    return all(
        passes(c, metrics) for c in optimisation.criteria if c.hard
    )


def aggregate_score(
    optimisation: OptimisationCriterion, metrics: dict[str, float],
) -> float:
    """Composite score per OptimisationCriterion.aggregation."""
    if optimisation.aggregation == "all":
        per = [1.0 if passes(c, metrics) else 0.0 for c in optimisation.criteria]
        return sum(per) / len(per) if per else 0.0
    # weighted
    total_weight = sum(max(0.0, c.weight) for c in optimisation.criteria)
    if total_weight == 0:
        return 0.0
    weighted = sum(
        max(0.0, c.weight) * continuous_score(c, metrics)
        for c in optimisation.criteria
    )
    return weighted / total_weight
