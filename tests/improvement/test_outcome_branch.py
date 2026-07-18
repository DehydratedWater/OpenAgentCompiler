"""Non-single-shot (outcome-judged) branch evaluator — orchestrator default.

Pins the v4 lesson: orchestrators are graded by OUTCOME of a full session, not a
hard path-match; the expected path is a soft hint; a prose-less dispatch-only run
shows the judge the trajectory. Judge is a stub — no live opencode/qwen.
"""

from __future__ import annotations

from open_agent_compiler.improvement.branch import (
    build_outcome_branch_evaluator,
    build_outcome_branch_loop,
    make_branch_outcome_judge_test,
)
from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.mutators import IdentityMutator
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.branch_model import BranchTest
from open_agent_compiler.testing.branch import BranchTrajectory
from open_agent_compiler.testing.evaluation import ToolCallRecord


class _StubJudge:
    """Records what it was asked to judge; returns a fixed score."""

    def __init__(self, score: float = 0.9) -> None:
        self.score = score
        self.seen: list[str] = []

    def judge(self, criteria, target, *, model=None):
        self.seen.append(str(target))
        return {"pass": self.score >= 0.7, "score": self.score, "reasoning": "ok"}


def _bt(name="b", path=("planner", "writer")) -> BranchTest:
    return BranchTest(name=name, entry_agent="orch", prompt="do the thing", path=path)


def test_outcome_judge_test_uses_soft_path_hint_not_path_match() -> None:
    jt = make_branch_outcome_judge_test(_bt())
    assert jt.name == "b::outcome"
    # exactly one evaluator, and it's the judge — NO PathOrderEvaluator
    assert len(jt.evaluators) == 1
    ev = jt.evaluators[0]
    assert ev.kind == "llm_judge"
    assert "planner -> writer" in ev.criteria          # path is a soft hint
    assert "both are fine" in ev.criteria               # not a hard match


def test_evaluator_judges_final_prose_output() -> None:
    judge = _StubJudge(0.9)

    def factory(_defn):
        return lambda _t: BranchTrajectory(output="a complete useful answer")

    ev = build_outcome_branch_evaluator([_bt()], factory, judge=judge)
    metrics = ev(ComponentVersion.of("orch", "agent", {"name": "orch"}))
    assert metrics["pass_rate"] == 1.0
    assert metrics["score_floor"] == 0.9
    assert judge.seen == ["a complete useful answer"]


def test_evaluator_shows_trajectory_when_no_prose() -> None:
    """Dispatch-only run: judge must see the spawned chain, not an empty turn."""
    judge = _StubJudge(0.8)

    def factory(_defn):
        return lambda _t: BranchTrajectory(
            output="",
            tool_calls=[ToolCallRecord(name="planner"), ToolCallRecord(name="writer")],
        )

    ev = build_outcome_branch_evaluator([_bt()], factory, judge=judge)
    ev(ComponentVersion.of("orch", "agent", {"name": "orch"}))
    assert "acted via: planner -> writer" in judge.seen[0]


def test_evaluator_populates_failures_sink_on_low_score() -> None:
    judge = _StubJudge(0.3)
    sink: list[dict] = []

    def factory(_defn):
        return lambda _t: BranchTrajectory(output="weak", tool_calls=[])

    ev = build_outcome_branch_evaluator(
        [_bt()], factory, judge=judge, failures_sink=sink,
    )
    metrics = ev(ComponentVersion.of("orch", "agent", {"name": "orch"}))
    assert metrics["pass_rate"] == 0.0
    assert len(sink) == 1
    assert sink[0]["score"] == 0.3
    assert "got_output" in sink[0]


def test_outcome_loop_runs_and_returns_winners() -> None:
    judge = _StubJudge(1.0)

    def factory(_defn):
        return lambda _t: BranchTrajectory(output="great answer")

    loop = build_outcome_branch_loop(
        entry_agent="orch",
        entry_definition={"name": "orch", "system_prompt": "be an orchestrator"},
        tests=[_bt()],
        invoker_factory=factory,
        mutators=[IdentityMutator()],
        criterion=OptimisationCriterion(
            name="g", criteria=(Criterion(kind="score_floor", target=1.0),),
        ),
        judge=judge,
        max_rounds=1,
    )
    result = loop.run()
    assert result.winners


# ---- tool-discipline / flailing signal on the branch evaluator ---------


class _NoteReadingJudge:
    """Drops the score when it SEES the forwarded TOOL DISCIPLINE note."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def judge(self, criteria, target, *, model=None):
        self.seen.append(str(target))
        score = 0.2 if "TOOL DISCIPLINE" in str(target) else 0.95
        return {"pass": score >= 0.7, "score": score, "reasoning": "ok"}


def test_branch_blocked_attempts_forwarded_to_judge_and_failures() -> None:
    judge = _NoteReadingJudge()
    sink: list[dict] = []

    def factory(_defn):
        return lambda _t: BranchTrajectory(
            output="an answer",
            blocked_tools=[("ls", "a rule prevents you from using ls"),
                           ("find", "a rule prevents you from using find")],
        )

    ev = build_outcome_branch_evaluator(
        [_bt()], factory, judge=judge, failures_sink=sink,
    )
    metrics = ev(ComponentVersion.of("orch", "agent", {"name": "orch"}))
    assert any("TOOL DISCIPLINE" in s and "ls" in s and "find" in s
               for s in judge.seen)
    assert metrics["score_floor"] < 0.7
    assert sink and sink[0]["blocked_attempts"] == 2
    assert set(sink[0]["blocked_tools"]) == {"ls", "find"}


def test_branch_session_error_labelled_to_judge_not_blank() -> None:
    judge = _NoteReadingJudge()
    sink: list[dict] = []

    def factory(_defn):
        return lambda _t: BranchTrajectory(
            output="", error="opencode error: Agent not found",
        )

    ev = build_outcome_branch_evaluator(
        [_bt()], factory, judge=judge, failures_sink=sink,
    )
    ev(ComponentVersion.of("orch", "agent", {"name": "orch"}))
    assert any("session ERRORED" in s and "Agent not found" in s
               for s in judge.seen)
    assert sink and "Agent not found" in sink[0]["error"]


def test_branch_flailing_scores_lower_than_clean() -> None:
    def _score(blocked):
        def factory(_defn):
            return lambda _t: BranchTrajectory(output="an answer",
                                               blocked_tools=blocked)
        ev = build_outcome_branch_evaluator(
            [_bt()], factory, judge=_NoteReadingJudge(),
        )
        return ev(ComponentVersion.of("orch", "agent", {"name": "orch"}))["score_floor"]

    clean = _score([])
    flailing = _score([("ls", "a rule prevents you from using ls")])
    assert flailing < clean, (flailing, clean)
