"""Evaluation primitives: RunContext, EvaluationResult, dispatcher.

The dispatcher dispatches an Evaluator instance to the right
implementation based on its `kind` discriminator. Each implementation
lives in open_agent_compiler/testing/evaluators/<family>.py and registers itself in the
EVALUATORS dict.

RunContext carries whatever the evaluator needs:
- output: the agent/tool output (any shape)
- tool_calls: list of recorded calls captured during a run
- permissions: the compiled permission dict (for permission_present/absent)
- llm_judge: optional injected judge client (for LLMJudgeEvaluator)

A RunContext doesn't have to populate every field — evaluators that need
a missing piece return a clean "skipped" result instead of crashing.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.model.core.test_model import AnyEvaluator, Evaluator


class ToolCallRecord(BaseModel):
    """One observed tool invocation during an AgentTest run.

    `error` carries the deny/error reason when the permission policy BLOCKED the
    call (e.g. "a rule prevents you from using ls") or the tool part errored —
    the tool-discipline signal a judge/rewriter needs to learn the model flailed
    on a forbidden tool. None for a clean call.
    """

    model_config = ConfigDict(frozen=False)

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str | None = None


class JudgeClient(Protocol):
    """Pluggable LLM judge interface used by LLMJudgeEvaluator (Phase 5.2b)."""

    def judge(self, criteria: str, target: Any, *, model: str | None = None) -> dict:
        """Return {pass: bool, score: float (0..1), reasoning: str}."""
        ...


class RunContext(BaseModel):
    """Everything an evaluator might want, all optional.

    `judge` is typed as Any because Pydantic can't validate bare Protocols
    without @runtime_checkable; the documented contract is JudgeClient
    (see Protocol above). Use a real JudgeClient implementation at the
    call site.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    output: Any = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    permissions: dict[str, Any] | None = None
    judge: Any = None
    extras: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    """Outcome of one Evaluator against one RunContext."""

    model_config = ConfigDict(frozen=False)

    evaluator_kind: str
    evaluator_name: str = ""
    passed: bool
    score: float = Field(
        default=1.0,
        description="Continuous score in [0, 1]. Pass/fail comes from `passed`.",
    )
    evidence: str = Field(
        default="",
        description="Human-readable explanation of what was checked + outcome.",
    )
    details: dict[str, Any] = Field(default_factory=dict)
    skipped: bool = False
    skip_reason: str = ""

    @classmethod
    def skip(cls, evaluator: Evaluator, reason: str) -> "EvaluationResult":
        return cls(
            evaluator_kind=evaluator.kind, evaluator_name=evaluator.name,
            passed=True, score=0.0, skipped=True, skip_reason=reason,
            evidence=f"skipped: {reason}",
        )

    @classmethod
    def from_check(
        cls, evaluator: Evaluator, passed: bool, *,
        evidence: str = "", score: float | None = None, details: dict | None = None,
    ) -> "EvaluationResult":
        return cls(
            evaluator_kind=evaluator.kind,
            evaluator_name=evaluator.name,
            passed=passed,
            score=score if score is not None else (1.0 if passed else 0.0),
            evidence=evidence,
            details=details or {},
        )


EvaluatorFn = Callable[[Evaluator, RunContext], EvaluationResult]
EVALUATORS: dict[str, EvaluatorFn] = {}


def register(kind: str):
    """Decorator: register a function as the implementation for an Evaluator kind."""

    def decorate(fn: EvaluatorFn) -> EvaluatorFn:
        EVALUATORS[kind] = fn
        return fn

    return decorate


def evaluate(evaluator: AnyEvaluator, context: RunContext) -> EvaluationResult:
    """Dispatch `evaluator` to its registered implementation."""
    impl = EVALUATORS.get(evaluator.kind)
    if impl is None:
        return EvaluationResult.skip(
            evaluator, f"no implementation registered for kind {evaluator.kind!r}"
        )
    return impl(evaluator, context)


# Importing the evaluator modules triggers their @register decorators.
from open_agent_compiler.testing.evaluators import deterministic, llm_judge  # noqa: F401, E402
