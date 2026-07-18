"""PathOrderEvaluator — ordered-subsequence check over a recorded chain.

This is the primitive behind branch tests: "did the orchestrator chain these
steps in this order". Covers ordered subsequence, interleaving, contiguity,
partial-credit scoring, and the empty-steps edge.
"""

from __future__ import annotations

from open_agent_compiler.model.core.test_model import PathOrderEvaluator
from open_agent_compiler.testing.evaluation import RunContext, ToolCallRecord, evaluate


def _ctx(*names: str) -> RunContext:
    return RunContext(tool_calls=[ToolCallRecord(name=n) for n in names])


def test_ordered_subsequence_passes_with_interleaving():
    ev = PathOrderEvaluator(steps=("analyze", "plan", "write"))
    ctx = _ctx("analyze", "noise", "plan", "other", "write")
    r = evaluate(ev, ctx)
    assert r.passed and r.score == 1.0


def test_out_of_order_fails_with_partial_credit():
    ev = PathOrderEvaluator(steps=("analyze", "plan", "write"))
    # plan precedes analyze: greedy matches analyze (step 0), then can't find
    # plan after it → stops. Longest in-order prefix = 1.
    ctx = _ctx("plan", "analyze", "write")
    r = evaluate(ev, ctx)
    assert not r.passed
    assert 0.0 < r.score < 1.0
    assert r.details["matched"] == 1


def test_missing_step_fails():
    ev = PathOrderEvaluator(steps=("analyze", "plan", "write"))
    # plan missing → prefix stops at analyze; write cannot count without plan.
    r = evaluate(ev, _ctx("analyze", "write"))
    assert not r.passed
    assert r.details["matched"] == 1


def test_contiguous_requires_adjacency():
    ev = PathOrderEvaluator(steps=("plan", "write"), contiguous=True)
    assert evaluate(ev, _ctx("plan", "write")).passed
    assert evaluate(ev, _ctx("plan", "noise", "write")).passed is False
    # contiguous is all-or-nothing on score
    assert evaluate(ev, _ctx("plan", "noise", "write")).score == 0.0


def test_empty_steps_is_vacuously_true():
    ev = PathOrderEvaluator(steps=())
    assert evaluate(ev, _ctx("anything")).passed


def test_exact_chain_scores_full():
    ev = PathOrderEvaluator(steps=("a", "b", "c"))
    r = evaluate(ev, _ctx("a", "b", "c"))
    assert r.passed and r.score == 1.0
    assert r.details["chain"] == ["a", "b", "c"]
