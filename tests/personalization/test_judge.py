"""Spec-seeded judge — success_criteria become the rubric / OptimisationCriterion."""

from __future__ import annotations

import pytest

from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.scoring import aggregate_score, metric_key
from open_agent_compiler.model.core.test_model import AgentTest, LLMJudgeEvaluator
from open_agent_compiler.personalization import (
    ClientSpec,
    build_client_criterion,
    build_client_judge_test,
    build_client_rubric,
)


def test_rubric_includes_goal_and_all_success_criteria(valid_spec: ClientSpec) -> None:
    rubric = build_client_rubric(valid_spec)
    assert valid_spec.goal in rubric
    for crit in valid_spec.success_criteria:
        assert crit in rubric


def test_rubric_caps_score_on_constraint_violation(valid_spec: ClientSpec) -> None:
    rubric = build_client_rubric(valid_spec)
    assert "HARD CONSTRAINTS" in rubric
    assert "Never promise a refund" in rubric
    assert "cannot score above 0.3" in rubric


def test_rubric_requires_success_criteria() -> None:
    spec = ClientSpec(goal="g")
    with pytest.raises(ValueError, match="no success_criteria"):
        build_client_rubric(spec)


def test_build_client_criterion_shape(valid_spec: ClientSpec) -> None:
    crit = build_client_criterion(valid_spec, target=0.8)
    assert isinstance(crit, OptimisationCriterion)
    assert len(crit.criteria) == 1
    c = crit.criteria[0]
    assert c.kind == "score_floor"
    assert c.target == 0.8
    assert c.scope == "by_evaluator"
    assert c.scope_value == "llm_judge"
    # the rubric is carried as the criterion's description (self-documenting)
    assert valid_spec.goal in crit.description


def test_criterion_metric_key_matches_judge_signal(valid_spec: ClientSpec) -> None:
    crit = build_client_criterion(valid_spec)
    key = metric_key(crit.criteria[0])
    assert key == "score_floor:by_evaluator:llm_judge"


def test_criterion_scores_against_judge_metrics(valid_spec: ClientSpec) -> None:
    crit = build_client_criterion(valid_spec, target=0.7)
    key = "score_floor:by_evaluator:llm_judge"
    # a candidate the judge scored 0.9 clears the 0.7 bar (full credit, capped 1.0)
    assert aggregate_score(crit, {key: 0.9}) == pytest.approx(1.0)
    # a candidate scored 0.35 lands proportionally below 1.0
    assert aggregate_score(crit, {key: 0.35}) == pytest.approx(0.5)


def test_build_client_judge_test_carries_rubric(valid_spec: ClientSpec) -> None:
    test = build_client_judge_test(
        valid_spec, prompt="Customer wants a refund — reply.", pass_threshold=0.75
    )
    assert isinstance(test, AgentTest)
    assert test.prompt == "Customer wants a refund — reply."
    assert len(test.evaluators) == 1
    ev = test.evaluators[0]
    assert isinstance(ev, LLMJudgeEvaluator)
    assert ev.pass_threshold == 0.75
    assert valid_spec.goal in ev.criteria
    assert valid_spec.success_criteria[0] in ev.criteria


def test_build_client_judge_test_requires_prompt(valid_spec: ClientSpec) -> None:
    with pytest.raises(ValueError, match="non-empty prompt"):
        build_client_judge_test(valid_spec, prompt="  ")


def test_judge_test_graded_by_stub_judge(valid_spec: ClientSpec) -> None:
    """The spec-built test is gradeable by a JudgeClient seam (mock judge)."""
    from open_agent_compiler.testing.evaluation import RunContext, evaluate

    class StubJudge:
        def judge(self, criteria, target, *, model=None):
            # 'good' if the response mentions the client's own success language
            score = 1.0 if "refund" not in str(target) else 0.2
            return {"score": score, "reasoning": "stub"}

    test = build_client_judge_test(valid_spec, prompt="reply to customer")
    ev = test.evaluators[0]
    ctx_good = RunContext(output="Here is your tracking link.", judge=StubJudge())
    res = evaluate(ev, ctx_good)
    assert res.passed is True
    assert res.score == pytest.approx(1.0)


def test_multi_step_criterion_matches_outcome_branch_metric(valid_spec: ClientSpec) -> None:
    """Regression: the multi_step promotion gate must match the BARE ``score_floor``
    that ``build_outcome_branch_evaluator`` emits. Otherwise the gate scopes to
    ``score_floor:by_evaluator:llm_judge`` (a key the branch evaluator never emits),
    ``continuous_score`` returns its neutral 0.5, and an orchestrator can NEVER clear
    ``target`` to promote. (Found rolling the personalization loop onto a
    production consumer.)
    """
    # exactly what build_outcome_branch_evaluator emits (bare, no per-evaluator scope)
    branch_metrics = {"score_floor": 0.9, "score_mean": 0.9, "pass_rate": 1.0}

    multi = build_client_criterion(valid_spec, target=0.7, multi_step=True)
    assert metric_key(multi.criteria[0]) == "score_floor"
    # the gate sees the real score and clears the bar
    assert aggregate_score(multi, branch_metrics) >= 0.7

    single = build_client_criterion(valid_spec, target=0.7, multi_step=False)
    assert metric_key(single.criteria[0]) == "score_floor:by_evaluator:llm_judge"
    # the bug: bare branch metrics don't match -> neutral 0.5 -> never promotes
    assert aggregate_score(single, branch_metrics) == pytest.approx(0.5)
