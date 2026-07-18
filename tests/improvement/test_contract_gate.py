"""Contract gate — the loop must optimise the REAL goal, not a text proxy.

Locks a production field lesson (docs/lessons/optimize-the-real-goal-not-text-correctness.md):
a candidate that produces beautiful assistant TEXT but never calls the required
delivery tool delivered NOTHING in production. These tests prove:

- a contract-HONORING candidate (calls the delivery tool / emits the deliverable)
  scores HIGH, while an otherwise-identical TEXT-ONLY candidate scores 0;
- the gate COMPOSES with the judge (the judge still grades the delivered payload);
- the regression: under a naive text-judge the text-only candidate WINS; under the
  contract gate the delivering candidate wins instead.

All mocked — no live opencode / qwen / z.ai.
"""

from __future__ import annotations

from open_agent_compiler.improvement import (
    ComponentVersion,
    ContractResult,
    RunOutcome,
    aggregate_score,
    all_of,
    contract_gate,
    Criterion,
    hard_pass,
    OptimisationCriterion,
    require_any_tool_called,
    require_artifact,
    require_outcome,
    require_subagent_dispatched,
    require_tool_called,
)
from open_agent_compiler.testing.evaluation import ToolCallRecord


# --- fixtures: two candidates that are TEXT-identical, delivery-different -----

def _version(name: str) -> ComponentVersion:
    return ComponentVersion.of(name, "agent", {"name": name})


# A naive base evaluator that grades ONLY the assistant text — the proxy that
# diverged from the real goal. Both candidates produce great text so both score
# high here; only the contract gate can tell them apart.
def _text_only_base(version: ComponentVersion) -> dict[str, float]:
    return {"score_floor": 0.95, "score_mean": 0.95, "pass_rate": 1.0}


# Run outcomes: the HONORING candidate calls emit_guidance; the TEXT-ONLY one
# produces identical prose but never delivers.
_DELIVERED = RunOutcome(
    tool_calls=[ToolCallRecord(name="python scripts/emit_guidance.py")],
    output="A complete, useful briefing (1253 chars)…",
)
_TEXT_ONLY = RunOutcome(
    tool_calls=[],  # NEVER delivered
    output="A complete, useful briefing (1253 chars)…",
)


def _outcome_for(version: ComponentVersion) -> RunOutcome:
    return _DELIVERED if "honoring" in version.component_id else _TEXT_ONLY


# --- predicates -------------------------------------------------------------

def test_require_tool_called_matches_by_substring() -> None:
    pred = require_tool_called("emit_guidance")
    assert pred(_DELIVERED).satisfied is True
    res = pred(_TEXT_ONLY)
    assert res.satisfied is False
    assert "CONTRACT BROKEN" in res.reason
    assert "emit_guidance" in res.reason


def test_require_artifact_checks_emission_and_content() -> None:
    pred = require_artifact("briefing", predicate=lambda p: bool(p))
    assert pred(RunOutcome(artifacts={"briefing": "payload"})).satisfied is True
    # emitted but empty → content check fails
    assert pred(RunOutcome(artifacts={"briefing": ""})).satisfied is False
    # never emitted
    assert pred(RunOutcome(artifacts={})).satisfied is False


def test_require_subagent_dispatched_falls_back_to_stdout() -> None:
    pred = require_subagent_dispatched("delivery")
    line = (
        '{"part":{"state":{"input":{"command":'
        '"opencode run --agent delivery-primary hi"}}}}'
    )
    assert pred(RunOutcome(stdout=line)).satisfied is True
    assert pred(RunOutcome(dispatch_chain=["planner"])).satisfied is False


def test_require_any_tool_called_accepts_alternatives() -> None:
    pred = require_any_tool_called(["emit_guidance", "send_briefing"])
    assert pred(_DELIVERED).satisfied is True
    assert pred(RunOutcome(tool_calls=[ToolCallRecord(name="send_briefing")])).satisfied
    assert pred(_TEXT_ONLY).satisfied is False


def test_all_of_requires_every_contract() -> None:
    pred = all_of(
        require_tool_called("emit_guidance"),
        require_artifact("briefing"),
    )
    ok = RunOutcome(
        tool_calls=[ToolCallRecord(name="emit_guidance")],
        artifacts={"briefing": "x"},
    )
    assert pred(ok).satisfied is True
    # tool called but no artifact → fails on the second contract
    half = RunOutcome(tool_calls=[ToolCallRecord(name="emit_guidance")])
    assert pred(half).satisfied is False


# --- the core principle: honoring beats text-only ---------------------------

def test_contract_honoring_scores_high_text_only_scores_zero() -> None:
    gated = contract_gate(
        _text_only_base,
        contract=require_tool_called("emit_guidance"),
        outcome_for=_outcome_for,
    )

    honoring = gated(_version("honoring-briefer"))
    text_only = gated(_version("text-only-briefer"))

    # The delivering candidate keeps its high quality score.
    assert honoring["score_floor"] == 0.95
    assert honoring["contract_satisfied"] == 1.0

    # The beautiful-but-undelivered candidate is FORCED to 0 on every score key.
    assert text_only["score_floor"] == 0.0
    assert text_only["score_mean"] == 0.0
    assert text_only["pass_rate"] == 0.0
    assert text_only["contract_satisfied"] == 0.0


def test_gate_records_failure_reason_for_the_teacher() -> None:
    sink: list[dict] = []
    gated = contract_gate(
        _text_only_base,
        contract=require_tool_called("emit_guidance"),
        outcome_for=_outcome_for,
        failures_sink=sink,
    )
    gated(_version("text-only-briefer"))
    assert len(sink) == 1
    entry = sink[0]
    assert entry["contract"] == "contract_satisfied"
    assert "CONTRACT BROKEN" in entry["reason"]
    assert entry["tool_calls"] == []  # the missing delivery is on the record

    # A delivering candidate records no failure.
    sink2: list[dict] = []
    gated2 = contract_gate(
        _text_only_base,
        contract=require_tool_called("emit_guidance"),
        outcome_for=_outcome_for,
        failures_sink=sink2,
    )
    gated2(_version("honoring-briefer"))
    assert sink2 == []


def test_gate_composes_with_judge_grading_the_delivered_payload() -> None:
    """The gate is the contract; the base evaluator still grades QUALITY.

    Two candidates both deliver (pass the gate) but one delivers a worse payload —
    the judge-driven base score must still discriminate them. The gate only zeroes
    NON-delivering candidates; it never flattens delivered-payload quality.
    """

    def judge_base(version: ComponentVersion) -> dict[str, float]:
        # mimic build_session_judge_evaluator grading the delivered payload
        score = 0.9 if "good" in version.component_id else 0.4
        return {
            "score_floor:by_evaluator:llm_judge": score,
            "score_floor": score, "score_mean": score, "pass_rate": 1.0,
        }

    def both_deliver(_v: ComponentVersion) -> RunOutcome:
        return _DELIVERED

    gated = contract_gate(
        judge_base,
        contract=require_tool_called("emit_guidance"),
        outcome_for=both_deliver,
    )
    good = gated(_version("good-payload"))
    weak = gated(_version("weak-payload"))

    # Both delivered, so both keep their judge score — quality still ranks them.
    assert good["contract_satisfied"] == 1.0
    assert weak["contract_satisfied"] == 1.0
    assert good["score_floor:by_evaluator:llm_judge"] == 0.9
    assert weak["score_floor:by_evaluator:llm_judge"] == 0.4
    assert good["score_floor"] > weak["score_floor"]


def test_require_outcome_is_an_alias_for_contract_gate() -> None:
    gated = require_outcome(
        _text_only_base,
        contract=require_tool_called("emit_guidance"),
        outcome_for=_outcome_for,
    )
    assert gated(_version("honoring-x"))["score_floor"] == 0.95
    assert gated(_version("text-only-x"))["score_floor"] == 0.0


# --- the regression: naive text-judge picks the wrong winner ----------------

def test_regression_text_judge_picks_undelivered_winner_gate_fixes_it() -> None:
    """Documents the failure mode and the fix.

    The TEXT-ONLY candidate has SLIGHTLY better prose (0.97 vs 0.92) but never
    delivers. Under the naive text-judge it WINS — exactly the production
    disaster. Under the contract gate it is forced to 0 and the delivering
    candidate wins.
    """
    # candidate prose scores under the naive text proxy
    proxy_scores = {"text-only-briefer": 0.97, "honoring-briefer": 0.92}

    def text_proxy(version: ComponentVersion) -> dict[str, float]:
        s = proxy_scores[version.component_id]
        return {"score_floor": s, "score_mean": s, "pass_rate": 1.0}

    criterion = OptimisationCriterion(
        name="quality",
        aggregation="weighted",
        criteria=(Criterion(kind="score_floor", target=1.0),),
    )

    honoring = _version("honoring-briefer")
    text_only = _version("text-only-briefer")

    # --- BEFORE: naive text-judge ranks the UNDELIVERED candidate first ---
    naive_h = text_proxy(honoring)
    naive_t = text_proxy(text_only)
    assert aggregate_score(criterion, naive_t) > aggregate_score(criterion, naive_h)

    # --- AFTER: contract gate forces the undelivered candidate to 0 ---
    gated = contract_gate(
        text_proxy,
        contract=require_tool_called("emit_guidance"),
        outcome_for=_outcome_for,
    )
    fixed_h = gated(honoring)
    fixed_t = gated(text_only)
    assert aggregate_score(criterion, fixed_h) > aggregate_score(criterion, fixed_t)
    assert aggregate_score(criterion, fixed_t) == 0.0


def test_gate_metric_is_hard_criterion_compatible() -> None:
    """`contract_satisfied` can gate a HARD criterion so undelivered = disqualified."""
    gated = contract_gate(
        _text_only_base,
        contract=require_tool_called("emit_guidance"),
        outcome_for=_outcome_for,
    )
    # Build a hard criterion that reads the contract metric directly.
    hard_crit = OptimisationCriterion(
        name="must-deliver",
        aggregation="all",
        criteria=(
            Criterion(
                name="contract_satisfied", kind="score_floor", target=1.0,
                hard=True, scope="by_name", scope_value="contract_satisfied",
            ),
        ),
    )
    # The gate emits the bare key; map it for by_name lookup.
    honoring = gated(_version("honoring-briefer"))
    text_only = gated(_version("text-only-briefer"))
    honoring["score_floor:by_name:contract_satisfied"] = honoring["contract_satisfied"]
    text_only["score_floor:by_name:contract_satisfied"] = text_only["contract_satisfied"]
    assert hard_pass(hard_crit, honoring) is True
    assert hard_pass(hard_crit, text_only) is False


# --- RunOutcome.from_run_result over a fake OpencodeRunResult ----------------

def test_run_outcome_from_run_result_pulls_chain_and_text() -> None:
    class _FakeResult:
        stdout = "irrelevant"

        def subagent_dispatch_chain(self):
            return [("delivery-primary", {"via": "spawn"})]

        def final_text(self):
            return "the prose"

    run = RunOutcome.from_run_result(_FakeResult())
    assert run.all_dispatched() == ["delivery-primary"]
    assert run.output == "the prose"
    assert require_subagent_dispatched("delivery")(run).satisfied is True


def test_contract_result_dataclass_shape() -> None:
    r = ContractResult(True, "ok")
    assert r.satisfied is True and r.reason == "ok"
