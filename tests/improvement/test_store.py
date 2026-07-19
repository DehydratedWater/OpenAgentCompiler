"""Run store: SQLite recording, queries, loop wiring, URL construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.improvement import (
    Criterion,
    IdentityMutator,
    IterativeLoop,
    OptimisationCriterion,
    OptimizationTarget,
    PromptPrefixMutator,
    RunStore,
    SqliteRunStore,
    open_store,
    promote,
    run_per_target_loops,
    version_from_candidate_row,
    write_snapshot,
)
from open_agent_compiler.improvement.version import ComponentVersion


def _baseline() -> ComponentVersion:
    return ComponentVersion.of(
        component_id="orch", kind="agent",
        definition={"name": "orch", "system_prompt": "be helpful"},
    )


def _criterion() -> OptimisationCriterion:
    return OptimisationCriterion(
        name="passes", criteria=(Criterion(kind="pass_rate", target=1.0, hard=True),),
    )


def _store(tmp_path: Path) -> SqliteRunStore:
    return SqliteRunStore(tmp_path / "improvement.db")


# ---- open_store --------------------------------------------------------


def test_open_store_default_path(tmp_path: Path) -> None:
    store = open_store(project_root=tmp_path)
    assert isinstance(store, SqliteRunStore)
    assert store.db_path == tmp_path / ".oac" / "improvement.db"
    assert store.db_path.exists()


def test_open_store_sqlite_url(tmp_path: Path) -> None:
    store = open_store(f"sqlite:///{tmp_path}/runs.db")
    assert isinstance(store, SqliteRunStore)
    assert store.db_path == tmp_path / "runs.db"


def test_open_store_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError, match="no run-store backend"):
        open_store("postgres://localhost/oac")


def test_sqlite_store_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(_store(tmp_path), RunStore)


# ---- loop wiring -------------------------------------------------------


def _run_loop(store: SqliteRunStore):
    return IterativeLoop(
        baseline=_baseline(),
        mutators=[IdentityMutator(), PromptPrefixMutator("CRITICAL: ")],
        criterion=_criterion(),
        evaluator=lambda v: {"pass_rate": 1.0},
        max_rounds=1,
        frontier_size=2,
        store=store,
        run_notes="unit-test",
    ).run()


def test_loop_records_run_and_candidates(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = _run_loop(store)

    runs = store.runs("orch")
    assert len(runs) == 1
    run = runs[0]
    assert run["notes"] == "unit-test"
    assert run["finished_at"] is not None
    assert run["winner_count"] == len(result.winners)

    rows = store.candidates(run_id=run["run_id"])
    assert rows  # baseline + mutated candidate at minimum
    hashes = {r["content_hash"] for r in rows}
    assert result.best().content_hash in hashes
    winners = [r for r in rows if r["winner"]]
    assert winners


def test_best_candidate_query(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run_loop(store)
    best = store.best_candidate("orch")
    assert best is not None
    assert best["metrics"]["pass_rate"] == 1.0


def test_version_roundtrip_from_row(tmp_path: Path) -> None:
    """The recomputed hash matches the stored one — definitions round-trip
    canonically through the database."""
    store = _store(tmp_path)
    result = _run_loop(store)
    winner_hashes = {w.content_hash for w in result.winners}
    for row in store.candidates(component_id="orch"):
        version = version_from_candidate_row(row)
        assert version.content_hash == row["content_hash"]
        assert version.metrics == {"pass_rate": 1.0}
    best = store.best_candidate("orch")
    assert best["content_hash"] in winner_hashes


# ---- per-target loops: store means finalized-export-only files ---------


def test_target_loops_with_store_write_only_best_winner(tmp_path: Path) -> None:
    store = _store(tmp_path)
    output = tmp_path / "improved"
    out = run_per_target_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator(), PromptPrefixMutator("A: "),
                  PromptPrefixMutator("B: ")],
        criterion=_criterion(),
        targets=[OptimizationTarget(harness="pi", model_class="fast")],
        evaluator_factory=lambda t: (lambda v: {"pass_rate": 1.0}),
        max_rounds=1,
        output=output,
        store=store,
    )
    target_dir = output / "orch" / "pi+fast"
    hash_files = [p for p in target_dir.glob("*.json") if p.name != "LATEST.json"]
    assert len(hash_files) == 1  # finalized export only, not every winner
    assert (target_dir / "LATEST.json").exists()
    # ...but the full history is in the database.
    rows = store.candidates(component_id="orch")
    assert len(rows) >= 3
    assert out["pi+fast"].loop_result.winners


def test_target_loop_run_rows_carry_target_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run_per_target_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator()],
        criterion=_criterion(),
        targets=[OptimizationTarget(harness="interactive")],
        evaluator_factory=lambda t: (lambda v: {"pass_rate": 1.0}),
        max_rounds=1,
        store=store,
    )
    runs = store.runs("orch")
    assert runs[0]["target"] == "interactive"


# ---- promotions --------------------------------------------------------


def test_promote_records_into_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snap_path = write_snapshot(_baseline(), tmp_path / "improved")
    promote(snap_path, tmp_path, target="pi+fast", store=store)
    promos = store.promotions("orch")
    assert len(promos) == 1
    assert promos[0]["slot"] == "pi+fast"
    assert promos[0]["content_hash"] == _baseline().content_hash


def test_compile_records_artifacts(tmp_path: Path) -> None:
    """CompileScript(store_url=...) records the build in the compiles table."""
    from open_agent_compiler.compiler.script import CompileScript
    from open_agent_compiler.model.core.agent_model import (
        AgentDefinition, AgentHeader, CompilationConfig, ModelParameters,
        TemplateSlot, TemplateTree,
    )
    from open_agent_compiler.model.core.agent_registry import AgentRegistry

    def factory():
        reg = AgentRegistry()
        agent = AgentDefinition(
            header=AgentHeader(agent_id="x", name="x"),
            usage_explanation_long="l", usage_explanation_short="s",
            system_prompt="hi",
        )
        aid = reg.register_agent("x", agent, ModelParameters(model_name="m"))
        reg.register_template(TemplateTree(
            name="t", slots=[TemplateSlot(name="primary", default_agent_id=aid)]))
        reg.create_compilation_config(CompilationConfig(name="c", template_name="t"))
        return reg

    db = tmp_path / "improvement.db"
    CompileScript(
        target=tmp_path / "build", factory=factory, config="c",
        dialect="codex", store_url=f"sqlite:///{db}",
    ).run()
    compiles = SqliteRunStore(db).compiles()
    assert len(compiles) == 1
    assert compiles[0]["dialect"] == "codex"
    assert compiles[0]["file_count"] >= 1
