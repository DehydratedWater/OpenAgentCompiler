"""LLMJudgeEvaluator + StubJudge + AnthropicJudge response parsing."""

from __future__ import annotations

from open_agent_compiler.model.core.test_model import LLMJudgeEvaluator
from open_agent_compiler.testing.evaluation import RunContext, evaluate
from open_agent_compiler.testing.judges import StubJudge
from open_agent_compiler.testing.judges.anthropic import _parse_judge_response


def test_llm_judge_skipped_when_no_judge() -> None:
    ev = LLMJudgeEvaluator(criteria="answer is correct")
    r = evaluate(ev, RunContext(output="hi"))
    assert r.skipped
    assert "no JudgeClient" in r.skip_reason


def test_llm_judge_stub_with_pass_response() -> None:
    judge = StubJudge(default={"pass": True, "score": 0.9, "reasoning": "good"})
    ev = LLMJudgeEvaluator(criteria="is polite")
    r = evaluate(ev, RunContext(output="hello", judge=judge))
    assert r.passed
    assert r.score == 0.9
    assert "good" in r.evidence
    assert len(judge.calls) == 1
    assert judge.calls[0]["criteria"] == "is polite"


def test_llm_judge_stub_with_fail_response() -> None:
    judge = StubJudge(default={"pass": False, "score": 0.1, "reasoning": "no"})
    ev = LLMJudgeEvaluator(criteria="is polite")
    r = evaluate(ev, RunContext(output="get lost", judge=judge))
    assert not r.passed


def test_llm_judge_uses_keyed_response_when_criteria_matches() -> None:
    judge = StubJudge(
        responses={
            "is polite": {"pass": True, "score": 1.0, "reasoning": "yes"},
            "is short": {"pass": False, "score": 0.0, "reasoning": "too long"},
        },
        default={"pass": False, "score": 0.5, "reasoning": "neither"},
    )
    polite = evaluate(
        LLMJudgeEvaluator(criteria="is polite"),
        RunContext(output="hello", judge=judge),
    )
    short = evaluate(
        LLMJudgeEvaluator(criteria="is short"),
        RunContext(output="hello", judge=judge),
    )
    other = evaluate(
        LLMJudgeEvaluator(criteria="is purple"),
        RunContext(output="hello", judge=judge),
    )
    assert polite.passed and short.passed is False
    assert other.passed is False  # falls back to default score 0.5 < 0.5? equals → pass via threshold? Let's check…


def test_llm_judge_threshold_used_when_pass_field_absent() -> None:
    judge = StubJudge(default={"score": 0.7, "reasoning": "ok"})  # no `pass` key
    ev = LLMJudgeEvaluator(criteria="x", pass_threshold=0.5)
    assert evaluate(ev, RunContext(output="y", judge=judge)).passed
    ev_strict = LLMJudgeEvaluator(criteria="x", pass_threshold=0.8)
    assert not evaluate(ev_strict, RunContext(output="y", judge=judge)).passed


def test_llm_judge_handles_judge_raising() -> None:
    class _Boom:
        def judge(self, criteria, target, *, model=None):
            raise RuntimeError("network down")

    ev = LLMJudgeEvaluator(criteria="x")
    r = evaluate(ev, RunContext(output="y", judge=_Boom()))
    assert not r.passed
    assert "network down" in r.evidence


def test_llm_judge_handles_non_dict_response() -> None:
    class _Junk:
        def judge(self, *a, **kw):
            return "not a dict"

    ev = LLMJudgeEvaluator(criteria="x")
    r = evaluate(ev, RunContext(output="y", judge=_Junk()))
    assert not r.passed
    assert "non-dict" in r.evidence


# ---- AnthropicJudge response parsing (no SDK needed) --------------------


def test_parse_judge_response_plain_json() -> None:
    out = _parse_judge_response('{"pass": true, "score": 0.9, "reasoning": "ok"}')
    assert out == {"pass": True, "score": 0.9, "reasoning": "ok"}


def test_parse_judge_response_strips_code_fence() -> None:
    out = _parse_judge_response(
        '```json\n{"pass": false, "score": 0.2, "reasoning": "no"}\n```'
    )
    assert out["pass"] is False
    assert out["score"] == 0.2


def test_parse_judge_response_non_json_returns_failing_verdict() -> None:
    out = _parse_judge_response("Sure, looks great!")
    assert out["pass"] is False
    assert out["score"] == 0.0
    assert "non-JSON" in out["reasoning"]
