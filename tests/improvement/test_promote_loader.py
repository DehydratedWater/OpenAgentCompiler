"""load_promoted_definition + apply_promoted_to_agent + chart helpers."""

from __future__ import annotations

from pathlib import Path


from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.chart import (
    render_per_candidate_table,
    render_round_progression,
)
from open_agent_compiler.improvement.loop import LoopResult, RoundResult
from open_agent_compiler.improvement.snapshot import (
    apply_promoted_to_agent,
    load_promoted_definition,
    load_promoted_snapshot,
    promote,
    write_snapshot,
)
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader


def _version(prompt: str = "v1") -> ComponentVersion:
    return ComponentVersion.of(
        component_id="weak-explainer", kind="agent",
        definition={
            "name": "weak-explainer",
            "system_prompt": prompt,
            "todo_mode": "lazy",
        },
        metrics={"pass_rate": 0.9},
    )


def _promote_into(project: Path, prompt: str = "BETTER") -> Path:
    snap_root = project / "improved"
    snap_path = write_snapshot(_version(prompt), snap_root)
    return promote(snap_path, project)


# ---- load_promoted_snapshot ---------------------------------------------


def test_load_promoted_snapshot_none_when_no_promotion(tmp_path: Path) -> None:
    assert load_promoted_snapshot("any", tmp_path) is None


def test_load_promoted_snapshot_returns_snapshot_when_present(tmp_path: Path) -> None:
    _promote_into(tmp_path, "BETTER")
    snap = load_promoted_snapshot("weak-explainer", tmp_path)
    assert snap is not None
    assert snap.version.definition["system_prompt"] == "BETTER"


def test_load_promoted_handles_slash_in_component_id(tmp_path: Path) -> None:
    # 'persona/orch' should map to .oac/promoted/persona__orch.json
    snap_root = tmp_path / "improved"
    v = ComponentVersion.of(
        component_id="persona/orch", kind="agent",
        definition={"name": "orch", "system_prompt": "X"},
    )
    snap_path = write_snapshot(v, snap_root)
    promote(snap_path, tmp_path)
    loaded = load_promoted_snapshot("persona/orch", tmp_path)
    assert loaded is not None


# ---- load_promoted_definition -------------------------------------------


def test_load_promoted_definition_returns_dict(tmp_path: Path) -> None:
    _promote_into(tmp_path, "BETTER")
    out = load_promoted_definition("weak-explainer", tmp_path)
    assert out is not None
    assert out["system_prompt"] == "BETTER"


def test_load_promoted_definition_none_when_no_promotion(tmp_path: Path) -> None:
    assert load_promoted_definition("any", tmp_path) is None


# ---- apply_promoted_to_agent --------------------------------------------


def _agent(prompt: str = "weak") -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(agent_id="x", name="x", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt=prompt,
        todo_mode="strict",
    )


def test_apply_promoted_returns_input_unchanged_when_no_promotion(tmp_path: Path) -> None:
    base = _agent("weak")
    out = apply_promoted_to_agent(base, "missing", tmp_path)
    assert out is base


def test_apply_promoted_merges_system_prompt(tmp_path: Path) -> None:
    _promote_into(tmp_path, "BETTER")
    base = _agent("weak")
    out = apply_promoted_to_agent(base, "weak-explainer", tmp_path)
    assert out.system_prompt == "BETTER"
    # Other fields preserved.
    assert out.header.name == "x"


def test_apply_promoted_only_copies_named_fields(tmp_path: Path) -> None:
    _promote_into(tmp_path, "BETTER")
    base = _agent("weak")
    # Restrict the fields list — even though 'todo_mode' is in the
    # promoted definition, it shouldn't be merged when not in `fields`.
    out = apply_promoted_to_agent(
        base, "weak-explainer", tmp_path, fields=("system_prompt",),
    )
    assert out.system_prompt == "BETTER"
    assert out.todo_mode == "strict"  # unchanged


# ---- chart rendering ---------------------------------------------------


def _result_with_rounds() -> tuple[LoopResult, OptimisationCriterion]:
    crit = OptimisationCriterion(
        name="t", criteria=(Criterion.for_named("m", "score_floor", 1.0),),
    )
    v0 = ComponentVersion.of(
        component_id="x", kind="agent", definition={"system_prompt": "baseline"},
        metrics={"score_floor:by_name:m": 0.5},
    )
    v1 = ComponentVersion.of(
        component_id="x", kind="agent", definition={"system_prompt": "round1"},
        parent_hash=v0.content_hash,
        metrics={"score_floor:by_name:m": 0.9},
        author="prompt-prefix",
    )
    v2 = ComponentVersion.of(
        component_id="x", kind="agent", definition={"system_prompt": "round2"},
        parent_hash=v1.content_hash,
        metrics={"score_floor:by_name:m": 1.0},
        author="llm-prompt-rewriter",
    )
    result = LoopResult(
        rounds=[
            RoundResult(round_index=0, candidates=[v1]),
            RoundResult(round_index=1, candidates=[v2]),
        ],
        winners=[v2, v1],
    )
    return result, crit


def test_render_round_progression_shows_score_per_round() -> None:
    result, crit = _result_with_rounds()
    out = render_round_progression(result, crit)
    assert "round 0" in out
    assert "round 1" in out
    assert "Final winner" in out
    assert "llm-prompt-rewriter" in out


def test_render_round_progression_handles_empty_round() -> None:
    crit = OptimisationCriterion(
        name="t", criteria=(Criterion.for_named("m", "score_floor", 1.0),),
    )
    result = LoopResult(
        rounds=[RoundResult(round_index=0, candidates=[])],
        winners=[],
    )
    out = render_round_progression(result, crit)
    assert "no new candidates" in out


def test_render_per_candidate_table_sorts_descending() -> None:
    result, crit = _result_with_rounds()
    out = render_per_candidate_table(result, crit)
    # llm-prompt-rewriter has higher score → appears first
    assert out.index("llm-prompt-rewriter") < out.index("prompt-prefix")


def test_render_per_candidate_table_empty_input() -> None:
    crit = OptimisationCriterion(
        name="t", criteria=(Criterion.for_named("m", "score_floor", 1.0),),
    )
    result = LoopResult(rounds=[], winners=[])
    assert render_per_candidate_table(result, crit) == "no candidates"
