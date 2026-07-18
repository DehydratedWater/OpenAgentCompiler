"""OptimisationCriterion + Criterion models."""

from __future__ import annotations

import pytest

from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion


def test_criterion_minimum_shape() -> None:
    c = Criterion(kind="pass_rate", target=1.0)
    assert c.scope == "any"
    assert c.weight == 1.0
    assert c.hard is False


def test_typed_scope_requires_scope_value() -> None:
    with pytest.raises(ValueError, match="requires scope_value"):
        Criterion(kind="pass_rate", target=1.0, scope="by_evaluator")
    with pytest.raises(ValueError, match="requires scope_value"):
        Criterion(kind="score_floor", target=0.8, scope="by_name")


def test_typed_scope_with_value_ok() -> None:
    c = Criterion(
        kind="score_floor", target=0.8,
        scope="by_evaluator", scope_value="llm_judge",
    )
    assert c.scope_value == "llm_judge"


def test_criterion_kinds_cover_design_set() -> None:
    expected = {"pass_rate", "score_floor", "latency_p95", "cost_ceiling", "determinism"}
    # Pick one of each — confirms the Literal covers each kind.
    for k in expected:
        Criterion(kind=k, target=1.0)


def test_optimisation_criterion_requires_at_least_one_criterion() -> None:
    with pytest.raises(ValueError, match="≥1 criterion"):
        OptimisationCriterion(name="oc", criteria=())


def test_optimisation_criterion_default_aggregation_is_all() -> None:
    oc = OptimisationCriterion(
        name="oc", criteria=(Criterion(kind="pass_rate", target=1.0),),
    )
    assert oc.aggregation == "all"


def test_optimisation_criterion_carries_multiple_criteria() -> None:
    oc = OptimisationCriterion(
        name="multi",
        aggregation="weighted",
        criteria=(
            Criterion(kind="pass_rate", target=1.0, hard=True),
            Criterion(kind="score_floor", target=0.8, scope="by_evaluator",
                       scope_value="llm_judge", weight=2.0),
            Criterion(kind="latency_p95", target=2.0),
        ),
    )
    assert len(oc.criteria) == 3
    assert oc.criteria[0].hard is True
    assert oc.criteria[1].weight == 2.0


def test_criterion_frozen_so_loop_can_share_instance() -> None:
    c = Criterion(kind="pass_rate", target=1.0)
    with pytest.raises(Exception):
        c.target = 0.5  # type: ignore[misc]
