"""FactRecallEvaluator: graded retrieval QA — fact recall + hallucination guard."""

from __future__ import annotations

from open_agent_compiler.model.core.test_model import FactRecallEvaluator, FactSpec
from open_agent_compiler.testing.evaluation import RunContext, evaluate


def _ev(**kw) -> FactRecallEvaluator:
    return FactRecallEvaluator(**kw)


def test_full_recall_passes_with_score_1() -> None:
    ev = _ev(facts=(FactSpec(any_of=("atenza",)), FactSpec(any_of=("36mg", "36 mg"))))
    r = evaluate(ev, RunContext(output="You took Atenza 36 mg on Tuesday."))
    assert r.passed
    assert r.score == 1.0
    assert r.details["missing"] == []


def test_partial_recall_scores_fraction_and_fails_default_threshold() -> None:
    ev = _ev(facts=(
        FactSpec(any_of=("atenza",)),
        FactSpec(any_of=("36mg", "36 mg")),
        FactSpec(any_of=("tuesday",)),
        FactSpec(any_of=("dr. nowak", "nowak")),
    ))
    r = evaluate(ev, RunContext(output="Atenza, 36mg."))
    assert not r.passed
    assert r.score == 0.5
    assert "tuesday" in r.details["missing"]


def test_pass_threshold_allows_partial_recall() -> None:
    ev = _ev(
        facts=(FactSpec(any_of=("a",)), FactSpec(any_of=("b",)), FactSpec(any_of=("zzz",))),
        pass_threshold=0.6,
    )
    r = evaluate(ev, RunContext(output="a and b are here"))
    assert r.passed
    assert round(r.score, 2) == 0.67


def test_alias_matching_any_of() -> None:
    ev = _ev(facts=(FactSpec(any_of=("thirty-six milligrams", "36 mg", "36mg")),))
    r = evaluate(ev, RunContext(output="the dose was 36mg"))
    assert r.passed
    assert r.details["recalled"] == ["36mg"]


def test_case_insensitive_by_default_and_opt_in_sensitive() -> None:
    insensitive = _ev(facts=(FactSpec(any_of=("ATENZA",)),))
    assert evaluate(insensitive, RunContext(output="atenza")).passed

    sensitive = _ev(facts=(FactSpec(any_of=("ATENZA",), case_sensitive=True),))
    assert not evaluate(sensitive, RunContext(output="atenza")).passed


def test_forbidden_content_zeroes_score_even_with_full_recall() -> None:
    ev = _ev(
        facts=(FactSpec(any_of=("atenza",)),),
        forbidden=("72mg",),
    )
    r = evaluate(ev, RunContext(output="Atenza 72mg"))  # fabricated dose
    assert not r.passed
    assert r.score == 0.0
    assert r.details["fabricated"] == ["72mg"]


def test_pure_no_hallucination_probe_no_facts() -> None:
    ev = _ev(forbidden=("as an ai", "i cannot access"))
    clean = evaluate(ev, RunContext(output="Here is what I found in your journal."))
    assert clean.passed and clean.score == 1.0

    dirty = evaluate(ev, RunContext(output="As an AI, I cannot access your data."))
    assert not dirty.passed and dirty.score == 0.0


def test_non_string_output_is_stringified() -> None:
    ev = _ev(facts=(FactSpec(any_of=("'status': 'done'",)),))
    r = evaluate(ev, RunContext(output={"status": "done"}))
    assert r.passed
