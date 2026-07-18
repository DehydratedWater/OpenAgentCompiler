"""Fleet harness — run per-agent and per-branch improvement loops at scale.

A large fleet (e.g. ~105 agents + every orchestrator branch in the
production deployment that motivated this module) needs each
unit to carry its OWN loop and have them all run, snapshot, and promote without
hand-writing the orchestration 200 times. This module is that orchestration
layer over the existing primitives (`IterativeLoop`, `build_branch_loop`,
snapshot/promote):

- one `ImprovementUnit` wraps a ready loop + its identity (agent or branch);
- `run_fleet(units, ...)` runs them **in parallel** (the recon flagged serial
  evaluation as the one real scale risk — ~thousands of eval calls), with
  **per-unit error isolation** so one bad unit can't sink the run;
- winners are **snapshotted**, and any winner clearing both `promote_threshold`
  AND the loop's hard criteria is **batch-promoted** into `.oac/promoted/`.

Tiering (mock gate → live promote) is entirely inside each loop's evaluator —
the harness just runs whatever loops it's given. Build per-agent loops with
`IterativeLoop`, per-branch loops with `build_branch_loop`, wrap each with
`agent_unit` / `branch_unit`, and hand the list to `run_fleet`.
"""

from __future__ import annotations

from typing import Any

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.improvement.branch import branch_component_id
from open_agent_compiler.improvement.loop import IterativeLoop
from open_agent_compiler.improvement.scoring import aggregate_score, hard_pass
from open_agent_compiler.improvement.snapshot import promote, write_round_winners, write_snapshot

UnitKind = Literal["agent", "branch"]


class ImprovementUnit(BaseModel):
    """One optimisable thing in the fleet, reduced to a runnable loop."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    unit_id: str
    kind: UnitKind
    loop: IterativeLoop


def agent_unit(agent_id: str, loop: IterativeLoop) -> ImprovementUnit:
    return ImprovementUnit(unit_id=agent_id, kind="agent", loop=loop)


def branch_unit(entry_agent: str, loop: IterativeLoop) -> ImprovementUnit:
    """Wrap a branch loop. unit_id is namespaced like the branch component id."""
    return ImprovementUnit(
        unit_id=branch_component_id(entry_agent), kind="branch", loop=loop,
    )


class UnitOutcome(BaseModel):
    """Result of optimising one unit."""

    model_config = ConfigDict(frozen=False)

    unit_id: str
    kind: UnitKind
    winner_hash: str | None = None
    winner_definition: dict[str, Any] | None = None
    winner_score: float = 0.0
    metrics: dict[str, float] = Field(default_factory=dict)
    snapshots: list[str] = Field(default_factory=list)
    promoted: bool = False
    promoted_path: str | None = None
    error: str | None = None


class FleetResult(BaseModel):
    outcomes: list[UnitOutcome] = Field(default_factory=list)

    def by_id(self, unit_id: str) -> UnitOutcome | None:
        return next((o for o in self.outcomes if o.unit_id == unit_id), None)

    def promoted(self) -> list[UnitOutcome]:
        return [o for o in self.outcomes if o.promoted]

    def failed(self) -> list[UnitOutcome]:
        return [o for o in self.outcomes if o.error is not None]

    def summary(self) -> dict[str, float | int]:
        ok = [o for o in self.outcomes if o.error is None]
        return {
            "units": len(self.outcomes),
            "succeeded": len(ok),
            "failed": len(self.failed()),
            "promoted": len(self.promoted()),
            "mean_winner_score": (
                sum(o.winner_score for o in ok) / len(ok) if ok else 0.0
            ),
        }


def _run_one(
    unit: ImprovementUnit,
    *,
    snapshots_dir: Path | None,
    project_root: Path | None,
    promote_threshold: float | None,
    run_label: str,
    client_id: str | None,
) -> UnitOutcome:
    outcome = UnitOutcome(unit_id=unit.unit_id, kind=unit.kind)
    try:
        result = unit.loop.run()
    except Exception as exc:  # isolate: one unit's failure must not sink the fleet
        outcome.error = f"{type(exc).__name__}: {exc}"
        return outcome

    criterion = unit.loop.criterion
    winners = result.winners
    if winners:
        best = max(winners, key=lambda v: aggregate_score(criterion, v.metrics))
        outcome.winner_hash = best.content_hash
        outcome.winner_definition = best.definition_copy()
        outcome.winner_score = aggregate_score(criterion, best.metrics)
        outcome.metrics = dict(best.metrics)

        if snapshots_dir is not None:
            outcome.snapshots = [
                str(p) for p in write_round_winners(
                    winners, snapshots_dir, run_label=run_label,
                )
            ]

        # Batch promote: only a winner that clears the score bar AND every hard
        # criterion (no regressions) is promoted.
        if (
            promote_threshold is not None
            and project_root is not None
            and outcome.winner_score >= promote_threshold
            and hard_pass(criterion, best.metrics)
        ):
            dest_root = snapshots_dir or (project_root / ".oac" / "snapshots")
            snap_path = write_snapshot(best, dest_root, notes=f"fleet:{run_label}")
            dest = promote(
                snap_path, project_root, force=True, client_id=client_id,
            )
            outcome.promoted = True
            outcome.promoted_path = str(dest)
    return outcome


def run_fleet(
    units: list[ImprovementUnit],
    *,
    snapshots_dir: Path | None = None,
    project_root: Path | None = None,
    promote_threshold: float | None = None,
    max_workers: int = 4,
    run_label: str = "",
    client_id: str | None = None,
    namespace: str | None = None,
) -> FleetResult:
    """Run every unit's loop, in parallel, with per-unit error isolation.

    - `snapshots_dir`: when set, each unit's winners are persisted there.
    - `project_root` + `promote_threshold`: when both set, a winner scoring
      ≥ threshold that also passes the loop's hard criteria is promoted into
      `<project_root>/.oac/promoted/` (or the isolation bucket, below).
    - `namespace`: a general run-isolation key — winners promote into the
      bucket `<project_root>/.oac/promoted/<namespace>/` and each unit's
      snapshots are isolated under `<snapshots_dir>/<namespace>/`, so N
      parallel runs of the SAME component never write over one another. Use it
      to run one agent against several MODELS at once (namespace = model slug),
      or any other parallel-run axis. `client_id` is the SaaS-tenant alias of
      the same mechanism; `namespace` wins when both are set. None = base run.
    - `max_workers`: thread pool size (loops are IO-bound when the evaluator
      shells out to live `opencode`; threads overlap that latency).
    """
    if not units:
        return FleetResult()

    # One general isolation key (model run / tenant / any parallel axis).
    iso = namespace or client_id

    # Isolate per-namespace snapshot/evaluator + promoted state in its own
    # subdir so parallel runs (e.g. one agent across models) never collide.
    effective_snapshots_dir = snapshots_dir
    if snapshots_dir is not None and iso:
        effective_snapshots_dir = snapshots_dir / iso.replace("/", "__")

    def _work(unit: ImprovementUnit) -> UnitOutcome:
        return _run_one(
            unit,
            snapshots_dir=effective_snapshots_dir,
            project_root=project_root,
            promote_threshold=promote_threshold,
            run_label=run_label,
            client_id=iso,
        )

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        outcomes = list(pool.map(_work, units))
    return FleetResult(outcomes=outcomes)


__all__ = [
    "ImprovementUnit",
    "UnitKind",
    "UnitOutcome",
    "FleetResult",
    "agent_unit",
    "branch_unit",
    "run_fleet",
]
