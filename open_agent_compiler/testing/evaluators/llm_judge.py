"""llm_judge evaluator — delegate to a JudgeClient on the RunContext.

The judge interface is intentionally simple: it returns
{pass: bool, score: float, reasoning: str}. The evaluator translates
that into an EvaluationResult.

Skip when no judge is configured on the context, so tests that don't
care about LLM-judged assertions can leave ctx.judge=None and still
run cleanly.
"""

from __future__ import annotations

from open_agent_compiler.model.core.test_model import LLMJudgeEvaluator
from open_agent_compiler.testing.evaluation import EvaluationResult, RunContext, register


@register("llm_judge")
def _llm_judge(ev: LLMJudgeEvaluator, ctx: RunContext) -> EvaluationResult:
    if ctx.judge is None:
        return EvaluationResult.skip(
            ev, "no JudgeClient configured on RunContext.judge",
        )
    try:
        verdict = ctx.judge.judge(
            ev.criteria, ctx.output, model=ev.judge_model,
        )
    except Exception as exc:  # noqa: BLE001 - judge failures shouldn't crash
        return EvaluationResult.from_check(
            ev, False,
            evidence=f"judge raised: {exc}",
            details={"error": str(exc)},
        )
    if not isinstance(verdict, dict):
        return EvaluationResult.from_check(
            ev, False,
            evidence=f"judge returned non-dict: {type(verdict).__name__}",
        )
    score = float(verdict.get("score", 0.0))
    explicit_pass = verdict.get("pass")
    if explicit_pass is None:
        passed = score >= ev.pass_threshold
    else:
        passed = bool(explicit_pass)
    return EvaluationResult.from_check(
        ev, passed,
        score=score,
        evidence=(
            f"llm_judge[{ev.criteria!r}] → pass={passed}"
            f" score={score} reasoning={verdict.get('reasoning', '')!r}"
        ),
        details={
            "criteria": ev.criteria,
            "pass_threshold": ev.pass_threshold,
            "judge_response": verdict,
        },
    )
