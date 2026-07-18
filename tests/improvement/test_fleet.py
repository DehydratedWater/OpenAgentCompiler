"""Fleet harness — parallel per-agent + per-branch loops, snapshot, promote.

Deterministic, no network: a toy evaluator scores a candidate by whether its
system_prompt carries a marker, so a prompt mutator makes it pass. Exercises
parallel execution, snapshotting, batch-promote gated on threshold + hard
criteria, and per-unit error isolation.
"""

from __future__ import annotations

from open_agent_compiler.improvement.branch import build_branch_loop
from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.fleet import (
    agent_unit,
    branch_unit,
    run_fleet,
)
from open_agent_compiler.improvement.loop import IterativeLoop
from open_agent_compiler.improvement.mutators import IdentityMutator, PromptPrefixMutator
from open_agent_compiler.improvement.snapshot import find_promoted_snapshot
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.branch_model import BranchTest
from open_agent_compiler.testing.branch import scripted_invoker

MARKER = "DO IT RIGHT."
CRIT = OptimisationCriterion(
    name="pass", criteria=(Criterion(kind="pass_rate", target=1.0, hard=True),),
)


def _agent_evaluator(version: ComponentVersion) -> dict[str, float]:
    ok = MARKER in version.definition.get("system_prompt", "")
    return {"pass_rate": 1.0 if ok else 0.0}


def _agent_loop(agent_id: str) -> IterativeLoop:
    baseline = ComponentVersion.of(
        agent_id, "agent", {"system_prompt": "weak"},
    )
    return IterativeLoop(
        baseline=baseline,
        mutators=[IdentityMutator(), PromptPrefixMutator(MARKER)],
        criterion=CRIT,
        evaluator=_agent_evaluator,
        max_rounds=2,
    )


def _branch_loop() -> IterativeLoop:
    test = BranchTest(
        name="chain", entry_agent="orch", prompt="do x then y",
        path=("a", "b"),
    )

    def factory(defn: dict):
        if MARKER in defn.get("system_prompt", ""):
            return scripted_invoker(["a", "b"], output="ok")
        return scripted_invoker(["b"], output="ok")  # wrong order

    return build_branch_loop(
        entry_agent="orch",
        entry_definition={"system_prompt": "route"},
        tests=[test],
        invoker_factory=factory,
        mutators=[IdentityMutator(), PromptPrefixMutator(MARKER)],
        criterion=CRIT,
        max_rounds=2,
    )


def test_fleet_runs_agents_and_branches_and_promotes(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    units = [
        agent_unit("agent-1", _agent_loop("agent-1")),
        agent_unit("agent-2", _agent_loop("agent-2")),
        branch_unit("orch", _branch_loop()),
    ]
    result = run_fleet(
        units,
        snapshots_dir=tmp_path / "snaps",
        project_root=project,
        promote_threshold=1.0,
        max_workers=3,
        run_label="t1",
    )
    s = result.summary()
    assert s["units"] == 3 and s["succeeded"] == 3 and s["failed"] == 0
    # every unit found the fix and got promoted
    assert s["promoted"] == 3
    # promoted snapshots actually landed in .oac/promoted/
    assert find_promoted_snapshot("agent-1", project) is not None
    assert find_promoted_snapshot("branch:orch", project) is not None
    # winners carry the marker
    for o in result.outcomes:
        assert o.winner_score == 1.0
        assert o.snapshots  # persisted


def test_below_threshold_is_not_promoted(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    # mutator that never adds the marker → never reaches pass_rate 1.0
    baseline = ComponentVersion.of("stuck", "agent", {"system_prompt": "weak"})
    loop = IterativeLoop(
        baseline=baseline,
        mutators=[IdentityMutator(), PromptPrefixMutator("irrelevant")],
        criterion=CRIT,
        evaluator=_agent_evaluator,
        max_rounds=2,
    )
    result = run_fleet(
        [agent_unit("stuck", loop)],
        snapshots_dir=tmp_path / "snaps",
        project_root=project,
        promote_threshold=1.0,
    )
    out = result.by_id("stuck")
    assert out is not None and out.error is None
    assert out.promoted is False
    assert find_promoted_snapshot("stuck", project) is None


def test_one_failing_unit_does_not_sink_the_fleet():
    class Boom(IterativeLoop):
        def run(self):  # type: ignore[override]
            raise RuntimeError("kaboom")

    good = agent_unit("good", _agent_loop("good"))
    bad = agent_unit(
        "bad",
        Boom(
            baseline=ComponentVersion.of("bad", "agent", {"system_prompt": "x"}),
            mutators=[IdentityMutator()],
            criterion=CRIT,
            evaluator=_agent_evaluator,
        ),
    )
    result = run_fleet([good, bad])
    assert result.by_id("good").error is None
    assert result.by_id("bad").error is not None
    assert "kaboom" in result.by_id("bad").error
    assert result.summary()["failed"] == 1


def test_empty_fleet_is_clean():
    assert run_fleet([]).summary()["units"] == 0


def test_fleet_promotes_into_client_bucket(tmp_path):
    """A per-client run promotes to .oac/promoted/<client_id>/ and isolates
    its snapshot dir; the base bucket stays empty."""
    project = tmp_path / "proj"
    project.mkdir()
    snaps = tmp_path / "snaps"
    result = run_fleet(
        [agent_unit("agent-1", _agent_loop("agent-1"))],
        snapshots_dir=snaps,
        project_root=project,
        promote_threshold=1.0,
        client_id="acme",
        run_label="t1",
    )
    assert result.summary()["promoted"] == 1
    # Promotion landed in the client bucket, resolvable with client_id...
    assert find_promoted_snapshot(
        "agent-1", project, client_id="acme",
    ) is not None
    # ...and the base bucket is empty (no leak across tenants).
    assert find_promoted_snapshot("agent-1", project) is None
    # Snapshots isolated under the client subdir.
    assert (snaps / "acme").exists()
    # The promoted file physically lives under the client bucket dir.
    assert (
        project / ".oac" / "promoted" / "acme" / "agent-1.json"
    ).exists()


def test_fleet_base_run_unchanged_with_client_id_none(tmp_path):
    """client_id=None promotes to the base bucket exactly as before."""
    project = tmp_path / "proj"
    project.mkdir()
    result = run_fleet(
        [agent_unit("agent-1", _agent_loop("agent-1"))],
        snapshots_dir=tmp_path / "snaps",
        project_root=project,
        promote_threshold=1.0,
        client_id=None,
    )
    assert result.summary()["promoted"] == 1
    assert find_promoted_snapshot("agent-1", project) is not None


def test_fleet_namespace_isolates_parallel_model_runs(tmp_path):
    """`namespace` is the general run-isolation key (the honest name for the
    client_id mechanism): two namespaced runs of the SAME agent promote into
    SEPARATE buckets and snapshot dirs, so N model-loops never collide."""
    project = tmp_path / "proj"
    project.mkdir()
    snaps = tmp_path / "snaps"
    for ns in ("qwen", "glm-4.7"):
        run_fleet(
            [agent_unit("agent-1", _agent_loop("agent-1"))],
            snapshots_dir=snaps,
            project_root=project,
            promote_threshold=1.0,
            namespace=ns,
            run_label=f"run-{ns}",
        )
    # Each namespace owns its promoted slot and snapshot dir...
    assert (project / ".oac" / "promoted" / "qwen" / "agent-1.json").exists()
    assert (project / ".oac" / "promoted" / "glm-4.7" / "agent-1.json").exists()
    assert (snaps / "qwen").exists() and (snaps / "glm-4.7").exists()
    # ...and the base bucket stays empty (no cross-namespace leak).
    assert find_promoted_snapshot("agent-1", project) is None


def test_namespace_takes_precedence_over_client_id(tmp_path):
    """When both are given, `namespace` wins (it's the general key)."""
    project = tmp_path / "proj"
    project.mkdir()
    run_fleet(
        [agent_unit("agent-1", _agent_loop("agent-1"))],
        snapshots_dir=tmp_path / "snaps",
        project_root=project,
        promote_threshold=1.0,
        namespace="model-x", client_id="tenant-y",
    )
    assert (project / ".oac" / "promoted" / "model-x" / "agent-1.json").exists()
    assert not (project / ".oac" / "promoted" / "tenant-y").exists()
