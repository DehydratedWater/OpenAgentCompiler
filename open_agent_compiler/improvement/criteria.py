"""OptimisationCriterion — what the improvement loop is trying to optimise.

A Criterion is one targeted measurement (e.g. "capability test pass-rate
≥ 1.0", "llm_judge score ≥ 0.8"). An OptimisationCriterion is a list
of Criteria composed with a logical aggregation rule (all / weighted).

The loop reads JSONL test artifacts (Phase 5.5) and scores candidate
variants against the criterion. Pareto-frontier candidates are kept.

This module is storage-only — scoring lives in open_agent_compiler/improvement/loop.py
(Phase 6.5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CriterionKind = Literal[
    "pass_rate",          # fraction of (non-skipped) tests passing
    "score_floor",        # minimum average score across matching tests
    "score_mean",         # mean score across matching tests (robust to 1 flaky probe)
    "score_quantile",     # a low-quantile score (e.g. p25) — soft floor that
                          # tolerates a few model-limited outliers but catches
                          # broad breakage. Higher is better.
    "latency_p95",        # p95 duration_s must be ≤ target
    "cost_ceiling",       # total cost across matching tests ≤ target (USD)
    "determinism",        # variance of score across N reruns ≤ target
    "tool_failure_rate",  # fraction of tool calls that errored ≤ target
]

ScopeKind = Literal[
    "any",
    "capability_tests",
    "tool_tests",
    "agent_tests",
    "by_evaluator",  # scoped to a specific evaluator kind ('llm_judge', 'equals', …)
    "by_name",       # scoped to test names matching a substring
]


class Criterion(BaseModel):
    """One targeted optimisation goal.

    Fields:
    - kind: which dimension to measure (see CriterionKind).
    - target: the threshold to hit (semantics depend on kind).
    - scope: which subset of test artifacts contribute.
    - scope_value: for 'by_evaluator' or 'by_name' scope, the matcher.
    - weight: relative importance when composed in a weighted aggregate.
    - hard: when True, this criterion must be met for a candidate to
      qualify regardless of weighted score. Use for "no regressions".
    """

    model_config = ConfigDict(frozen=True)

    name: str = ""
    kind: CriterionKind
    target: float
    scope: ScopeKind = "any"
    scope_value: str = ""
    weight: float = 1.0
    hard: bool = False

    @model_validator(mode="after")
    def _scope_value_required_when_typed(self) -> "Criterion":
        if self.scope in ("by_evaluator", "by_name") and not self.scope_value:
            raise ValueError(
                f"Criterion.scope={self.scope!r} requires scope_value"
            )
        return self

    @classmethod
    def for_named(
        cls, name: str, kind: "CriterionKind", target: float,
        *, weight: float = 1.0, hard: bool = False,
    ) -> "Criterion":
        """Build a Criterion that scopes itself by name.

        Shorthand for:
            Criterion(name=name, kind=kind, target=target, weight=weight,
                      hard=hard, scope='by_name', scope_value=name)

        Encourages the pattern where the criterion's `name` matches the
        suffix of the metric key produced by the evaluator (which is
        what the metric_key function expects under scope='by_name').
        Use this when your evaluator emits per-test metrics like
        'score_floor:by_name:response-length'.
        """
        return cls(
            name=name, kind=kind, target=target,
            weight=weight, hard=hard,
            scope="by_name", scope_value=name,
        )


AggregationKind = Literal["all", "weighted"]


class OptimisationCriterion(BaseModel):
    """A bundle of Criterion + how they're aggregated into one decision.

    Aggregation rules:
    - 'all': every soft criterion must pass; weighted score is the mean
      of per-criterion 0/1.
    - 'weighted': criteria are scored continuously (0..1); the aggregate
      is the weight-normalized sum. Hard criteria still must pass.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    aggregation: AggregationKind = "all"
    criteria: tuple[Criterion, ...] = Field(default_factory=tuple)
    description: str = ""

    @model_validator(mode="after")
    def _at_least_one_criterion(self) -> "OptimisationCriterion":
        if not self.criteria:
            raise ValueError(
                f"OptimisationCriterion {self.name!r} must list ≥1 criterion"
            )
        return self
