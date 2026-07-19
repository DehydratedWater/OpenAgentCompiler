"""Per-target improvement: one IterativeLoop per (harness × model_class) target.

`split_loop.run_per_class_loops` tunes the same logical agent per
*model class* — but always evaluated on one harness (whatever the
supplied evaluator shells out to). This module widens that single axis
into an **optimization target**: a (harness, model_class) pair, where
harness is a compile dialect ("opencode" / "pi" / "codex"), the
in-process "interactive" tier, or any consumer-defined label.

The core promise this enables: *define the agent once (with its tests
and benchmarks), then run autoloops to adapt it to each harness and
model it will actually run on.* A tiny fast model on pi wants a
different prompt than an analytical model on opencode; the interactive
LangChain runner strips worker scaffolding, so its winning prompt is
different again. Each target gets its own loop, its own winners, its own
snapshot directory, and its own promotion slot:

    improved/<component>/<target-key>/<hash>.json      (snapshots)
    .oac/promoted/<component>__<target-key>.json       (after promote --target)

Target keys are `<harness>+<class>` ("pi+fast", "opencode+analytical"),
or just `<harness>` when the target has no model_class. Promotion
resolution falls back target → model_class → default (see snapshot.py),
so a target-specific winner takes precedence when one exists and the
compile degrades gracefully when it doesn't.

The evaluator is built per target by an `EvaluatorFactory` — typically
closing over `harness_eval.get_runner(target.harness, build_dir)` for
compiled harnesses, or `interactive_eval.build_interactive_evaluator`
for the "interactive" tier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.improvement.store import RunStore

from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.loop import Evaluator, IterativeLoop, LoopResult
from open_agent_compiler.improvement.mutators import Mutator, MutationContext
from open_agent_compiler.improvement.snapshot import Snapshot
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.split_profile import SplitProfile

INTERACTIVE_HARNESS = "interactive"


class OptimizationTarget(BaseModel):
    """One (harness, model_class) cell of the adaptation matrix."""

    model_config = ConfigDict(frozen=True)

    harness: str = Field(
        description=(
            "Where candidates are evaluated: a compile dialect"
            " ('opencode' / 'pi' / 'codex'), the in-process 'interactive'"
            " tier, or any consumer-defined label."
        ),
    )
    model_class: str | None = Field(
        default=None,
        description=(
            "SplitProfile class this target tunes for ('fast' /"
            " 'analytical' / …). None = the harness's single/default model."
        ),
    )
    preset_id: str | None = Field(
        default=None,
        description="ModelPreset name the class resolves to (bookkeeping).",
    )

    @property
    def key(self) -> str:
        """Filesystem-safe slot key: '<harness>+<class>' or '<harness>'."""
        if self.model_class:
            return f"{self.harness}+{self.model_class}"
        return self.harness


EvaluatorFactory = Callable[[OptimizationTarget], Evaluator]


class PerTargetResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    target: OptimizationTarget
    loop_result: LoopResult


def targets_from_split_profile(
    harnesses: list[str], split_profile: SplitProfile,
) -> list[OptimizationTarget]:
    """The full harness × class cross product for a SplitProfile.

    ['opencode', 'pi'] × {fast, analytical} → four targets. Order is
    harness-major so per-harness builds can be prepared once per group.
    """
    return [
        OptimizationTarget(
            harness=harness, model_class=class_name, preset_id=preset.name,
        )
        for harness in harnesses
        for class_name, preset in split_profile.class_map.items()
    ]


def _baseline_for_target(
    baseline: ComponentVersion, target: OptimizationTarget,
) -> ComponentVersion:
    """A copy of `baseline` stamped with the target it is tuned for.

    model_class lands on the definition (SplitProfile reads it at
    compile time); the full target key goes to _oac_meta so the
    snapshot file records which harness+model the winner was tuned on.
    """
    defn = dict(baseline.definition)
    if target.model_class:
        defn["model_class"] = target.model_class
    meta = dict(defn.get("_oac_meta") or {})
    meta["target"] = target.key
    meta["harness"] = target.harness
    if target.preset_id:
        meta["preset_id"] = target.preset_id
    defn["_oac_meta"] = meta
    return ComponentVersion.of(
        component_id=baseline.component_id,
        kind=baseline.kind,
        definition=defn,
        author=f"target:{target.key}",
    )


def run_per_target_loops(
    *,
    baseline: ComponentVersion,
    mutators: list[Mutator],
    criterion: OptimisationCriterion,
    targets: list[OptimizationTarget],
    evaluator_factory: EvaluatorFactory,
    max_rounds: int = 3,
    frontier_size: int = 3,
    output: Path | None = None,
    mutation_context: MutationContext | None = None,
    store: RunStore | None = None,
) -> dict[str, PerTargetResult]:
    """One IterativeLoop per target; results keyed by `target.key`.

    When `output` is set, each target's winners are snapshotted under
    <output>/<component>/<target-key>/<hash>.json (LATEST.json
    alongside), ready for `oac promote --target <target-key>`.

    When `store` is ALSO set, the intermediate history (every round,
    candidate, and metric) is recorded to the database and the file
    output shrinks to the finalized export only — one best-winner
    snapshot per target (LATEST.json + its hash file). The database is
    the observability surface; the single JSON is what gets promoted,
    loaded, and version-controlled.

    `mutation_context` is forwarded into every loop so LLM-backed
    mutators (LLMPromptRewriter, ImprovementAgentMutator) keep their
    configured clients — without it they silently no-op.
    """
    results: dict[str, PerTargetResult] = {}
    for target in targets:
        target_baseline = _baseline_for_target(baseline, target)
        loop = IterativeLoop(
            baseline=target_baseline,
            mutators=mutators,
            criterion=criterion,
            evaluator=evaluator_factory(target),
            max_rounds=max_rounds,
            frontier_size=frontier_size,
            mutation_context=mutation_context,
            store=store,
            run_notes=f"target:{target.key}",
        )
        loop_out = loop.run()
        if output is not None:
            safe_component = baseline.component_id.replace("/", "__")
            target_dir = output / safe_component / target.key
            target_dir.mkdir(parents=True, exist_ok=True)
            label = f"{criterion.name}:{target.key}"
            if store is not None:
                # Intermediates live in the store — export the finalized
                # winner only.
                to_write = [loop_out.best()] if loop_out.best() else []
            else:
                to_write = loop_out.winners
            for v in to_write:
                snap = Snapshot(version=v, notes=label)
                path = target_dir / f"{v.content_hash[:12]}.json"
                path.write_text(snap.model_dump_json(indent=2))
                (target_dir / "LATEST.json").write_text(
                    snap.model_dump_json(indent=2)
                )
        results[target.key] = PerTargetResult(
            target=target, loop_result=loop_out,
        )
    return results
