"""IterativeLoop — mutate → evaluate → score → promote → repeat.

The loop is decoupled from how candidates are actually *evaluated*:
the user supplies an `evaluator` callable that takes a ComponentVersion
and returns a metrics dict. Real consumers wire that to: substitute
the candidate into the registry → compile → run `oac test` → read the
JSONL artifacts → aggregate metrics. For tests, a deterministic
evaluator function is enough.

Each round:
1. Take the current frontier (initial = baseline only).
2. For every (frontier_version × mutator) pair, produce a candidate.
3. Evaluate every candidate's metrics.
4. Register the candidate in the registry (parent_hash linked).
5. Update each candidate's metrics field on its registry entry (via
   re-register because ComponentVersion is frozen — see helpers below).
6. Drop candidates failing any hard criterion.
7. Score the rest; keep the top-N by aggregate_score.

The loop terminates when max_rounds is hit OR when a round produces no
new candidates (every mutator returned None or every candidate was a
duplicate of one already registered).
"""

from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.mutators import Mutator, MutationContext
from open_agent_compiler.improvement.scoring import aggregate_score, hard_pass
from open_agent_compiler.improvement.version import (
    ComponentRegistry,
    ComponentVersion,
)

Evaluator = Callable[[ComponentVersion], dict[str, float]]


class RoundResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    round_index: int
    candidates: list[ComponentVersion] = Field(default_factory=list)
    survivors: list[ComponentVersion] = Field(default_factory=list)
    scores: dict[str, float] = Field(
        default_factory=dict,
        description="content_hash → aggregate_score for this round's candidates.",
    )


class LoopResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    rounds: list[RoundResult] = Field(default_factory=list)
    winners: list[ComponentVersion] = Field(default_factory=list)
    archive: list[ComponentVersion] = Field(default_factory=list)

    def best(
        self, *, metric: str = "score_floor",
    ) -> ComponentVersion | None:
        """Pick the winner with the highest score on `metric`.

        Returns None when there are no winners. The default metric
        matches the convention that every Criterion writes a
        score-shaped value under this key; pass `metric="..."` to
        rank on a different criterion's metric instead.
        """
        if not self.winners:
            return None
        return max(
            self.winners,
            key=lambda v: v.metrics.get(metric, float("-inf")),
        )


def _with_metrics(version: ComponentVersion, metrics: dict[str, float]) -> ComponentVersion:
    """Frozen-aware: return a copy with the new metrics dict."""
    return version.model_copy(update={"metrics": metrics})


class IterativeLoop(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    baseline: ComponentVersion
    mutators: list[Mutator]
    criterion: OptimisationCriterion
    evaluator: Evaluator
    registry: ComponentRegistry = Field(default_factory=ComponentRegistry)
    max_rounds: int = 3
    frontier_size: int = 3
    mutation_context: MutationContext | None = None

    def run(self) -> LoopResult:
        result = LoopResult()
        # Make sure baseline is in the registry + has metrics.
        self._ensure_baseline()
        frontier: list[ComponentVersion] = [
            self.registry.get(self.baseline.content_hash)  # type: ignore[list-item]
        ]
        ctx = self.mutation_context or MutationContext(
            registry=self.registry, criterion=self.criterion,
        )

        for round_index in range(self.max_rounds):
            round_out = RoundResult(round_index=round_index)
            for parent in frontier:
                for mutator in self.mutators:
                    candidate = mutator.mutate(parent, ctx)
                    if candidate is None:
                        continue
                    if self.registry.get(candidate.content_hash) is not None:
                        continue
                    metrics = self.evaluator(candidate)
                    candidate = _with_metrics(candidate, metrics)
                    self.registry.register(candidate)
                    round_out.candidates.append(candidate)
                    round_out.scores[candidate.content_hash] = aggregate_score(
                        self.criterion, candidate.metrics,
                    )

            if not round_out.candidates:
                result.rounds.append(round_out)
                break

            survivors = [
                c for c in round_out.candidates if hard_pass(self.criterion, c.metrics)
            ]
            survivors.sort(
                key=lambda c: aggregate_score(self.criterion, c.metrics),
                reverse=True,
            )
            round_out.survivors = survivors[: self.frontier_size]
            result.rounds.append(round_out)
            # Update frontier for next round.
            frontier = round_out.survivors or [self.baseline]
            # If no survivor advanced past the baseline, stop early.
            if not round_out.survivors:
                break

        # Collate winners (Pareto-ish: top by aggregate score among
        # everything ever produced for this component).
        all_versions = self.registry.history(self.baseline.component_id)
        scored = sorted(
            all_versions,
            key=lambda v: aggregate_score(self.criterion, v.metrics),
            reverse=True,
        )
        result.winners = scored[: self.frontier_size]
        result.archive = [
            v for v in all_versions if v not in result.winners
        ]
        return result

    def _ensure_baseline(self) -> None:
        if self.registry.get(self.baseline.content_hash) is None:
            # Evaluate baseline so winners ranking sees its metrics.
            baseline_metrics = self.evaluator(self.baseline)
            baseline_with = _with_metrics(self.baseline, baseline_metrics)
            self.registry.register(baseline_with)
