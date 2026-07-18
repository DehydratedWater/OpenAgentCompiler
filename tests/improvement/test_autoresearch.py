"""Autoresearch — wrapping arbitrary callables in the improvement loop."""

from __future__ import annotations

import pytest

from open_agent_compiler.improvement import (
    ChoiceFieldMutator,
    Criterion,
    NumericFieldMutator,
    OptimisationCriterion,
    Probe,
    ProbeOutcome,
    build_callable_evaluator,
    metrics_from_results,
    optimize_callable,
    run_probe,
    run_probes,
)
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.test_model import (
    LLMJudgeEvaluator,
    SubstringEvaluator,
    ToolCalledEvaluator,
)
from open_agent_compiler.testing.evaluation import ToolCallRecord


# ── run_probe ──────────────────────────────────────────────────────────


def test_run_probe_scores_plain_string_output() -> None:
    probe = Probe(
        probe_id="greets",
        payload="hi",
        evaluators=(SubstringEvaluator(needle="hello"),),
    )
    ok = run_probe(probe, lambda payload: f"hello {payload}")
    assert ok.passed and ok.score == 1.0

    bad = run_probe(probe, lambda payload: "nope")
    assert not bad.passed and bad.score == 0.0


def test_run_probe_isolates_executable_exceptions() -> None:
    probe = Probe(probe_id="boom", evaluators=(SubstringEvaluator(needle="x"),))

    def explode(payload):
        raise RuntimeError("policy divided by zero")

    result = run_probe(probe, explode)
    assert not result.passed
    assert result.score == 0.0
    assert "policy divided by zero" in (result.error or "")
    assert result.evaluations == []


def test_run_probe_consumes_probe_outcome_tool_calls() -> None:
    probe = Probe(
        probe_id="delivers",
        evaluators=(ToolCalledEvaluator(tool_name="emit_guidance"),),
    )

    def deliver(payload) -> ProbeOutcome:
        return ProbeOutcome(
            output="done",
            tool_calls=[ToolCallRecord(name="emit_guidance", args={})],
        )

    assert run_probe(probe, deliver).passed


def test_run_probe_without_evaluators_is_an_existence_probe() -> None:
    probe = Probe(probe_id="runs-clean")
    assert run_probe(probe, lambda p: "anything").score == 1.0
    assert not run_probe(probe, _raiser).passed


def _raiser(payload):
    raise ValueError("nope")


def test_run_probe_passes_judge_through_to_llm_judge_evaluator() -> None:
    class FakeJudge:
        def judge(self, criteria, target, *, model=None):
            return {"pass": True, "score": 0.8, "reasoning": "fine"}

    probe = Probe(
        probe_id="judged",
        evaluators=(LLMJudgeEvaluator(criteria="is it varied?"),),
    )
    result = run_probe(probe, lambda p: "text", judge=FakeJudge())
    assert result.passed
    assert result.score == pytest.approx(0.8)


# ── metric aggregation ─────────────────────────────────────────────────


def test_metrics_shape_mirrors_branch_evaluator() -> None:
    probes = [
        Probe(probe_id="a", evaluators=(SubstringEvaluator(needle="ok"),)),
        Probe(probe_id="b", weight=3.0,
              evaluators=(SubstringEvaluator(needle="never"),)),
    ]
    results = run_probes(probes, lambda p: "ok")
    metrics = metrics_from_results(results)
    assert metrics["pass_rate"] == 0.5
    assert metrics["score_floor"] == 0.0
    # weighted mean: (1*1 + 0*3) / 4
    assert metrics["score_mean"] == pytest.approx(0.25)
    assert metrics["score_floor:by_name:a"] == 1.0
    assert metrics["score_floor:by_name:b"] == 0.0
    assert metrics_from_results([]) == {}


def test_callable_evaluator_rebuilds_executable_from_definition() -> None:
    probes = [Probe(probe_id="t", evaluators=(SubstringEvaluator(needle="lo"),))]

    def factory(definition):
        return lambda payload: definition["reply"]

    evaluator = build_callable_evaluator(probes, factory)
    good = ComponentVersion.of("policy", "prompt", {"reply": "hello"})
    bad = ComponentVersion.of("policy", "prompt", {"reply": "hi"})
    assert evaluator(good)["pass_rate"] == 1.0
    assert evaluator(bad)["pass_rate"] == 0.0


# ── full loop ──────────────────────────────────────────────────────────


def test_optimize_callable_tunes_a_policy_knob() -> None:
    # A toy delivery policy: it only "delivers" when its cooldown is short
    # enough for the probe's scenario. Baseline cooldown is too long; the
    # NumericFieldMutator must shrink it until probes pass.
    probes = [
        Probe(
            probe_id="idle-30min",
            payload={"idle_minutes": 30},
            evaluators=(SubstringEvaluator(needle="deliver"),),
        ),
        Probe(
            probe_id="idle-45min",
            payload={"idle_minutes": 45},
            evaluators=(SubstringEvaluator(needle="deliver"),),
        ),
    ]

    def factory(definition):
        def policy(payload):
            if payload["idle_minutes"] >= definition["cooldown_minutes"]:
                return "deliver nudge"
            return "skip"
        return policy

    result = optimize_callable(
        component_id="checker:cooldown",
        # One ×0.5 step away from passing: the loop drops candidates that
        # fail a hard criterion and halts on an all-failing round, so a
        # multi-step descent needs a soft (weighted) criterion instead.
        baseline_definition={"cooldown_minutes": 60},
        executable_factory=factory,
        probes=probes,
        mutators=[NumericFieldMutator("cooldown_minutes", scale=0.5, minimum=5)],
        criterion=OptimisationCriterion(
            name="delivers",
            criteria=(Criterion(kind="pass_rate", target=1.0, hard=True),),
        ),
        max_rounds=4,
    )
    best = result.best(metric="pass_rate")
    assert best is not None
    assert best.metrics["pass_rate"] == 1.0
    assert best.definition["cooldown_minutes"] <= 30
    # Lineage: the winner descends from the baseline.
    assert best.parent_hash is not None


# ── field mutators ─────────────────────────────────────────────────────


def _version(definition: dict) -> ComponentVersion:
    return ComponentVersion.of("p", "prompt", definition)


def test_numeric_field_mutator_scales_and_clamps() -> None:
    from open_agent_compiler.improvement.mutators import MutationContext

    ctx = MutationContext()
    m = NumericFieldMutator("limits.cooldown", scale=0.5, minimum=10)
    out = m.mutate(_version({"limits": {"cooldown": 60}}), ctx)
    assert out is not None and out.definition["limits"]["cooldown"] == 30

    clamped = m.mutate(_version({"limits": {"cooldown": 15}}), ctx)
    assert clamped is not None and clamped.definition["limits"]["cooldown"] == 10

    # Already at the clamp → no change → None.
    assert m.mutate(_version({"limits": {"cooldown": 10}}), ctx) is None
    # Missing path / non-numeric / bool → None.
    assert m.mutate(_version({"limits": {}}), ctx) is None
    assert m.mutate(_version({"limits": {"cooldown": "x"}}), ctx) is None
    assert m.mutate(_version({"limits": {"cooldown": True}}), ctx) is None


def test_numeric_field_mutator_delta_and_list_paths() -> None:
    from open_agent_compiler.improvement.mutators import MutationContext

    m = NumericFieldMutator("tiers.1.budget", delta=2, maximum=10)
    out = m.mutate(
        _version({"tiers": [{"budget": 1}, {"budget": 7}]}), MutationContext(),
    )
    assert out is not None
    assert out.definition["tiers"][1]["budget"] == 9
    assert out.definition["tiers"][0]["budget"] == 1


def test_numeric_field_mutator_requires_exactly_one_step() -> None:
    with pytest.raises(ValueError):
        NumericFieldMutator("x")
    with pytest.raises(ValueError):
        NumericFieldMutator("x", scale=2.0, delta=1.0)


def test_choice_field_mutator_rotates_choices() -> None:
    from open_agent_compiler.improvement.mutators import MutationContext

    ctx = MutationContext()
    m = ChoiceFieldMutator("mode", ["gentle", "direct", "playful"])
    out = m.mutate(_version({"mode": "gentle"}), ctx)
    assert out is not None and out.definition["mode"] == "direct"
    # Unknown current value snaps to the first choice.
    out2 = m.mutate(_version({"mode": "???"}), ctx)
    assert out2 is not None and out2.definition["mode"] == "gentle"
    # Missing path → None.
    assert m.mutate(_version({}), ctx) is None


def test_mutator_lineage_and_author_names() -> None:
    from open_agent_compiler.improvement.mutators import MutationContext

    parent = _version({"cooldown_minutes": 60})
    m = NumericFieldMutator("cooldown_minutes", scale=2.0)
    child = m.mutate(parent, MutationContext())
    assert child is not None
    assert child.parent_hash == parent.content_hash
    assert child.author == "num:cooldown_minutes*2.0"
