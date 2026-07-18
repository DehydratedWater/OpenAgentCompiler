"""Regression: a real-mutation branch winner must snapshot + promote cleanly.

The bug (blocked v4 orchestrator/branch promotions): every branch unit errored
at snapshot/promote-WRITE time with

    ValidationError: content_hash for 'branch:<entry>' does not match
    stable_content_hash(definition). Construct via ComponentVersion.of(...)

even though evaluation worked (the ``score=0.000`` was ``run_fleet``'s default
for an ERRORED unit, not a real score).

Root cause was framework-level: ``ComponentVersion.of`` stored the definition by
*shallow copy*, so a child version aliased its parent's nested mutable
substructure (the lists/dicts inside ``extra_tools`` / ``agent_tests`` etc. that
``AgentDefinition.model_dump()`` produces). Anything that later mutated one of
those shared objects in place — a downstream mutator or a live invoker compiling
the candidate — silently changed another version's stored ``definition`` *after*
its ``content_hash`` had been computed, leaving a stale hash that only blew up
when the winner was serialized into a ``Snapshot`` at write/promote time.

Crucially this needs a *real, definition-changing* mutator: with a trivial
identity mutator the winner == baseline and the hash happens to match, which is
why the earlier regression test passed yet the live run failed. This test uses a
prompt-rewriting mutator AND an invoker that mutates the (shared) definition in
place — exactly the live shape — and drives it through ``build_outcome_branch_loop``
+ the real ``run_fleet`` snapshot/promote path.

Pure / deterministic — no live opencode, qwen, or z.ai.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.improvement.branch import (
    branch_component_id,
    build_outcome_branch_loop,
)
from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.fleet import branch_unit, run_fleet
from open_agent_compiler.improvement.mutators import Mutator, MutationContext
from open_agent_compiler.improvement.snapshot import find_promoted_snapshot, read_snapshot
from open_agent_compiler.improvement.version import ComponentVersion, stable_content_hash
from open_agent_compiler.model.core.branch_model import BranchTest
from open_agent_compiler.testing.branch import BranchTrajectory

GRADED = OptimisationCriterion(
    name="lift", aggregation="weighted",
    criteria=(Criterion(kind="score_floor", target=1.0, weight=1.0),),
)


class _RealPromptRewriter(Mutator):
    """A mutator that actually CHANGES the definition every round.

    Mirrors the live GLM prompt rewriter: it edits ``system_prompt`` so each
    winner is a genuinely-mutated child (never == baseline), which is the
    condition under which the stale-hash bug fires.
    """

    name = "real-rewriter"

    def __init__(self) -> None:
        super().__init__(name=self.name)
        self._n = 0

    def mutate(self, version: ComponentVersion, ctx: MutationContext):
        if version.kind != "agent":
            return None
        self._n += 1
        defn = dict(version.definition)
        defn["system_prompt"] = (defn.get("system_prompt") or "") + f" v{self._n}"
        return ComponentVersion.of(
            component_id=version.component_id, kind=version.kind,
            definition=defn, parent_hash=version.content_hash, author=self.name,
        )


def _model_dump_shaped_definition() -> dict:
    """An orchestrator definition shaped like ``AgentDefinition.model_dump()``:

    nested mutable lists/dicts (and a tuple, as model_dump emits for tuple
    fields) that ``.of`` must NOT alias across versions.
    """
    return {
        "name": "orch",
        "system_prompt": "be an orchestrator",
        # nested mutable structures, like extra_tools / agent_tests dumps:
        "extra_tools": [{"header": {"name": "t", "rules": ("r1", "r2")}}],
        "agent_tests": [{"name": "t0", "evaluators": ({"kind": "llm_judge"},)}],
    }


class _MutatingInvokerJudge:
    """An invoker+judge that MUTATES the candidate's definition in place.

    A live branch invoker receives ``version.definition`` and compiles a
    candidate from it; if any step aliases + mutates that dict's nested objects
    (the real-world failure), and ``.of`` shallow-copied, the mutation would
    propagate to sibling versions and staleify their hashes. This stub forces
    that in-place mutation so the test deterministically exercises the path.
    """

    def factory(self, definition: dict):
        # Mutate a NESTED shared object in place — the dangerous pattern.
        if definition.get("extra_tools"):
            definition["extra_tools"][0]["header"]["injected"] = True

        def invoke(_test):
            return BranchTrajectory(output="a complete, useful answer")

        return invoke

    def judge(self, criteria, target, *, model=None):
        return {"pass": True, "score": 1.0, "reasoning": "ok"}


def _build_unit():
    mj = _MutatingInvokerJudge()
    loop = build_outcome_branch_loop(
        entry_agent="orch",
        entry_definition=_model_dump_shaped_definition(),
        tests=[BranchTest(name="b", entry_agent="orch", prompt="do the thing",
                          path=("a", "b"))],
        invoker_factory=mj.factory,
        mutators=[_RealPromptRewriter()],
        criterion=GRADED,
        judge=mj,
        max_rounds=2,
    )
    return branch_unit("orch", loop)


def test_real_mutation_branch_winner_snapshots_and_promotes(tmp_path: Path) -> None:
    """The whole point: a real-mutation branch winner snapshots with a content
    hash that matches its definition, and promotes — no ValidationError.

    FAILS before the fix (winners snapshot-write throws the stale-hash
    ValidationError, surfaced as ``UnitOutcome.error`` and ``score=0.000``),
    PASSES after.
    """
    snapshots = tmp_path / "snaps"
    project = tmp_path / "proj"
    result = run_fleet(
        [_build_unit()],
        snapshots_dir=snapshots,
        project_root=project,
        promote_threshold=0.5,
        max_workers=1,
        run_label="reg",
    )

    outcome = result.by_id(branch_component_id("orch"))
    assert outcome is not None
    # 1. No error — the stale-hash ValidationError is what we're fixing.
    assert outcome.error is None, outcome.error
    # 2. It actually evaluated (not the errored-unit 0.000 default).
    assert outcome.winner_score >= 0.5
    # 3. It snapshotted, and every snapshot's stored hash matches its definition.
    assert outcome.snapshots
    for p in outcome.snapshots:
        snap = read_snapshot(Path(p))
        assert snap.version.content_hash == stable_content_hash(
            snap.version.definition
        )
    # 4. It promoted, and the promoted snapshot reloads cleanly (validator passes).
    assert outcome.promoted
    promoted = find_promoted_snapshot(
        branch_component_id("orch"), project,
    )
    assert promoted is not None
    assert promoted.version.content_hash == stable_content_hash(
        promoted.version.definition
    )


def test_of_does_not_alias_parent_nested_definition() -> None:
    """Unit-level guard: a child built from a parent's definition must NOT share
    nested mutable objects, so an in-place mutation of one can't staleify the
    other's content_hash.
    """
    base = ComponentVersion.of("orch", "agent", _model_dump_shaped_definition())
    child = ComponentVersion.of(
        "orch", "agent", base.definition, parent_hash=base.content_hash,
    )
    assert base.definition["extra_tools"] is not child.definition["extra_tools"]
    # Mutate the parent's nested object in place; child's hash stays valid.
    base.definition["extra_tools"][0]["header"]["x"] = 1
    assert child.content_hash == stable_content_hash(child.definition)
