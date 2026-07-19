"""`oac versions` — list / show / load / unload / rollback / apply-source."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.cli.main import main
from open_agent_compiler.improvement import (
    Criterion,
    IdentityMutator,
    IterativeLoop,
    OptimisationCriterion,
    PromptPrefixMutator,
    SqliteRunStore,
    find_promoted_snapshot,
)
from open_agent_compiler.improvement.version import ComponentVersion


def _seed_store(project: Path) -> SqliteRunStore:
    store = SqliteRunStore(project / ".oac" / "improvement.db")
    baseline = ComponentVersion.of(
        component_id="orch", kind="agent",
        definition={"name": "orch", "system_prompt": "be helpful"},
    )
    IterativeLoop(
        baseline=baseline,
        mutators=[IdentityMutator(), PromptPrefixMutator("CRITICAL: ")],
        criterion=OptimisationCriterion(
            name="passes",
            criteria=(Criterion(kind="pass_rate", target=1.0, hard=True),),
        ),
        evaluator=lambda v: {"pass_rate": 1.0},
        max_rounds=1,
        store=store,
    ).run()
    return store


def _best_hash(store: SqliteRunStore) -> str:
    return store.best_candidate("orch")["content_hash"]


def test_versions_list(tmp_path: Path, capsys) -> None:
    _seed_store(tmp_path)
    rc = main(["versions", "list", "orch", "--project", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "hash" in out
    assert "W" in out  # at least one winner flagged


def test_versions_list_without_store_explains(tmp_path: Path, capsys) -> None:
    rc = main(["versions", "list", "orch", "--project", str(tmp_path)])
    assert rc == 2
    assert "no run store" in capsys.readouterr().out


def test_versions_load_unload_roundtrip(tmp_path: Path, capsys) -> None:
    store = _seed_store(tmp_path)
    best = _best_hash(store)

    rc = main(["versions", "load", "orch", best[:10],
               "--project", str(tmp_path), "--target", "pi+fast"])
    assert rc == 0
    promoted = find_promoted_snapshot("orch", tmp_path, target="pi+fast")
    assert promoted is not None
    assert promoted.version.content_hash == best

    rc = main(["versions", "unload", "orch",
               "--project", str(tmp_path), "--target", "pi+fast"])
    assert rc == 0
    assert find_promoted_snapshot("orch", tmp_path, target="pi+fast") is None


def test_versions_rollback_restores_previous(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    rows = store.candidates(component_id="orch")
    hashes = [r["content_hash"] for r in rows]
    first, second = hashes[0], hashes[-1]
    assert first != second

    main(["versions", "load", "orch", first[:10], "--project", str(tmp_path)])
    main(["versions", "load", "orch", second[:10], "--project", str(tmp_path),
          "--force"])
    current = find_promoted_snapshot("orch", tmp_path)
    assert current.version.content_hash == second

    rc = main(["versions", "rollback", "orch", "--project", str(tmp_path)])
    assert rc == 0
    rolled = find_promoted_snapshot("orch", tmp_path)
    assert rolled.version.content_hash == first


def test_versions_show(tmp_path: Path, capsys) -> None:
    store = _seed_store(tmp_path)
    best = _best_hash(store)
    rc = main(["versions", "show", "orch", best[:8], "--project", str(tmp_path)])
    assert rc == 0
    assert '"definition"' in capsys.readouterr().out


def test_versions_apply_source(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    # Load the mutated winner (prompt differs from the python baseline).
    winner = store.best_candidate("orch")
    main(["versions", "load", "orch", winner["content_hash"][:10],
          "--project", str(tmp_path)])

    agents_py = tmp_path / "agents.py"
    agents_py.write_text(
        "from open_agent_compiler import AgentDefinition, AgentHeader\n"
        "A = AgentDefinition(\n"
        "    header=AgentHeader(agent_id='orch', name='orch'),\n"
        "    usage_explanation_long='l', usage_explanation_short='s',\n"
        "    system_prompt='be helpful',\n"
        ")\n"
    )
    rc = main(["versions", "apply-source", "orch", str(agents_py),
               "--project", str(tmp_path)])
    assert rc == 0
    assert winner["definition"]["system_prompt"] in agents_py.read_text()
