"""Per-variant improvement: run IterativeLoop once per SplitProfile class.

A SplitProfile assigns different ModelPresets to agents declaring
different model_class values ('fast' / 'analytical' / 'vision').
Sometimes the same logical agent benefits from *different* prompts /
sampling settings depending on the model it runs on (a tiny fast
model wants tight instructions; an analytical model wants room to
reason).

run_per_class_loops drives one IterativeLoop per class entry. Each
loop produces its own winner set, snapshotted under
<output>/<component>/<class>/<hash>.json so the user can promote the
right variant for the right preset.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.loop import Evaluator, IterativeLoop, LoopResult
from open_agent_compiler.improvement.mutators import Mutator, MutationContext
from open_agent_compiler.improvement.snapshot import Snapshot
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.split_profile import SplitProfile


def _baseline_for_class(
    baseline: ComponentVersion, class_name: str, preset_id: str,
) -> ComponentVersion:
    """Return a copy of `baseline` whose definition declares model_class.

    The mutated definition records the class binding so the snapshot
    file knows which preset it was tuned for.
    """
    defn = dict(baseline.definition)
    defn["model_class"] = class_name
    defn.setdefault("_oac_meta", {})["preset_id"] = preset_id
    return ComponentVersion.of(
        component_id=baseline.component_id,
        kind=baseline.kind,
        definition=defn,
        author=f"split:{class_name}",
    )


class PerClassResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    class_name: str
    preset_id: str
    loop_result: LoopResult


def run_per_class_loops(
    *,
    baseline: ComponentVersion,
    mutators: list[Mutator],
    criterion: OptimisationCriterion,
    evaluator: Evaluator,
    split_profile: SplitProfile,
    max_rounds: int = 3,
    frontier_size: int = 3,
    output: Path | None = None,
    mutation_context: MutationContext | None = None,
) -> dict[str, PerClassResult]:
    """One IterativeLoop per class entry in split_profile.class_map.

    When output is set, snapshots are written under
    <output>/<component>/<class>/<hash>.json for each class's winners
    (LATEST.json sits alongside).

    `mutation_context` is forwarded into each per-class loop so
    LLM-backed mutators (LLMPromptRewriter, ImprovementAgentMutator)
    can access their configured clients. Without forwarding, those
    mutators silently no-op for lack of a configured llm.
    """
    results: dict[str, PerClassResult] = {}
    for class_name, preset in split_profile.class_map.items():
        class_baseline = _baseline_for_class(baseline, class_name, preset.name)
        loop = IterativeLoop(
            baseline=class_baseline,
            mutators=mutators,
            criterion=criterion,
            evaluator=evaluator,
            max_rounds=max_rounds,
            frontier_size=frontier_size,
            mutation_context=mutation_context,
        )
        loop_out = loop.run()
        if output is not None:
            safe_component = baseline.component_id.replace("/", "__")
            class_dir = output / safe_component / class_name
            class_dir.mkdir(parents=True, exist_ok=True)
            label = f"{criterion.name}:{class_name}"
            for v in loop_out.winners:
                snap = Snapshot(version=v, notes=label)
                path = class_dir / f"{v.content_hash[:12]}.json"
                path.write_text(snap.model_dump_json(indent=2))
                (class_dir / "LATEST.json").write_text(snap.model_dump_json(indent=2))
        results[class_name] = PerClassResult(
            class_name=class_name,
            preset_id=preset.name,
            loop_result=loop_out,
        )
    return results
