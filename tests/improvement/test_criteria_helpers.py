"""Criterion.for_named helper."""

from __future__ import annotations

from open_agent_compiler.improvement.criteria import Criterion
from open_agent_compiler.improvement.scoring import metric_key, passes


def test_for_named_sets_scope_and_value() -> None:
    c = Criterion.for_named("response-length", "score_floor", 1.0)
    assert c.scope == "by_name"
    assert c.scope_value == "response-length"
    assert c.name == "response-length"


def test_for_named_metric_key_matches_evaluator_convention() -> None:
    c = Criterion.for_named("response-length", "score_floor", 1.0)
    assert metric_key(c) == "score_floor:by_name:response-length"


def test_for_named_roundtrip_with_passes() -> None:
    c = Criterion.for_named("len", "score_floor", 1.0)
    assert passes(c, {"score_floor:by_name:len": 1.0})
    assert not passes(c, {"score_floor:by_name:len": 0.5})
    # missing → soft skip
    assert passes(c, {})


def test_for_named_passes_through_weight_and_hard() -> None:
    c = Criterion.for_named("len", "pass_rate", 1.0, weight=3.5, hard=True)
    assert c.weight == 3.5
    assert c.hard is True
