"""BranchTest — a test (and optimisation target) for a multi-agent *branch*.

A leaf `AgentTest` exercises one agent. But a fleet's real behaviour lives in
its **branches**: an orchestrator handed a task that forces it to chain several
subagents / tools in sequence (e.g. `persona/orchestrator` → `context_analyzer`
→ `priority_planner` → `todo` tool). The interesting failure modes — wrong
hand-off order, a skipped step, a subagent dispatched that shouldn't be — only
show up when the *path* is driven end-to-end.

A `BranchTest` is therefore scoped to an **entry agent** plus an expected
ordered dispatch chain (`path`), and is evaluated over the recorded trajectory
of the whole run — not a single agent's output. It is deliberately NOT embedded
on `AgentDefinition` (it spans agents); branches are registered at the fleet /
registry level and discovered there.

Two evaluation tiers (matching the project's both-tier decision):
- deterministic: subagents are replaced by `subagent_mocks` canned outputs, so
  the chain is reproducible with no model calls — used to gate every
  optimisation round;
- live: the same test driven through real `opencode` (no mocks) before a winner
  is promoted.

The runner (open_agent_compiler/testing/branch.py) abstracts the tier behind a `BranchInvoker`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from open_agent_compiler.model.core.test_model import AnyEvaluator, Turn


class StepContract(BaseModel):
    """Per-step assertions evaluated *inside* a branch run.

    A `BranchTest` judges the joint trajectory (order + final output) — it
    can't say anything about what one subagent RECEIVED or PRODUCED when the
    orchestrator dispatched it. That gap means a subagent only ever gets
    tested solo, never in its actual delegation context ("food_suggester must
    see the dietary restrictions the orchestrator was given"). A StepContract
    closes it: for every recorded dispatch of `step`, `input_evaluators` run
    against the call's args and `output_evaluators` against the call's
    output, and the results fold into the branch's pass/score — so branch
    optimisation rounds are gated on subagent discipline too.
    """

    model_config = ConfigDict(frozen=True)

    step: str = Field(description="Subagent / tool name this contract binds to.")
    input_evaluators: tuple[AnyEvaluator, ...] = Field(
        default=(),
        description="Run against each matching call's `args` dict.",
    )
    output_evaluators: tuple[AnyEvaluator, ...] = Field(
        default=(),
        description="Run against each matching call's `output`.",
    )
    required: bool = Field(
        default=True,
        description=(
            "When True, the branch FAILS if `step` was never dispatched;"
            " when False an undisached step just skips this contract."
        ),
    )

    @model_validator(mode="after")
    def _has_assertions(self) -> "StepContract":
        if not self.input_evaluators and not self.output_evaluators and not self.required:
            raise ValueError(
                f"StepContract for {self.step!r} asserts nothing: add evaluators"
                " or keep required=True (presence check)."
            )
        return self


class BranchTest(BaseModel):
    """End-to-end test for one orchestration branch.

    `path` is the expected ordered chain of dispatched subagent / tool names.
    It compiles to a `PathOrderEvaluator` automatically, so the common case
    ("did the orchestrator chain these steps in this order") needs no explicit
    evaluator. Add `evaluators` for assertions on the joint final output
    (substring / llm_judge / …) or extra tool-call checks.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    entry_agent: str = Field(
        description="Agent id of the branch root (the orchestrator driven).",
    )
    prompt: str = Field(
        default="",
        description="Single-turn task that forces the chain. Mutually exclusive with `turns`.",
    )
    turns: tuple[Turn, ...] = Field(
        default=(),
        description="Multi-turn variant; threads session state across turns.",
    )
    path: tuple[str, ...] = Field(
        default=(),
        description=(
            "Expected ordered dispatch chain (subagent / tool names). Becomes a"
            " PathOrderEvaluator. Empty means 'no ordering assertion'."
        ),
    )
    contiguous_path: bool = Field(
        default=False,
        description="Require `path` steps to be adjacent (strict pipeline) vs. an ordered subsequence.",
    )
    subagent_mocks: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Deterministic tier: name → canned output for each dispatched"
            " subagent/tool, so the branch runs reproducibly with no model"
            " calls. Ignored by the live tier."
        ),
    )
    evaluators: tuple[AnyEvaluator, ...] = Field(
        default=(),
        description="Extra assertions on the joint trajectory / final output.",
    )
    step_contracts: tuple[StepContract, ...] = Field(
        default=(),
        description=(
            "Per-step input/output assertions evaluated against each recorded"
            " dispatch of the named subagent/tool within this branch run."
        ),
    )
    access_profile: str | None = None
    mock_profile: str | None = None
    timeout_s: float = 120.0

    @model_validator(mode="after")
    def _prompt_xor_turns(self) -> "BranchTest":
        if self.prompt and self.turns:
            raise ValueError(
                f"BranchTest {self.name!r} cannot set both `prompt` and `turns`."
            )
        if not self.prompt and not self.turns:
            raise ValueError(
                f"BranchTest {self.name!r} must set either `prompt` or `turns`."
            )
        return self

    @property
    def is_multi_turn(self) -> bool:
        return bool(self.turns)

    def all_turns(self) -> tuple[Turn, ...]:
        if self.turns:
            return self.turns
        return (Turn(prompt=self.prompt),)
