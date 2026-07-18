"""Test definitions embeddable on agents, tools, and skills.

Three test kinds:

1. CapabilityTest — pure introspection over the compiled artifact:
   "agent X has tool Y enabled / skill Z disabled / mcp blocked / etc."
   No LLM, no tool execution, no I/O. Fastest, runs in milliseconds.

2. ToolTest — exercise a tool's handler under a mock binding:
   "given this input, the tool's mock_response (or actual handler in
   no-mock mode) returns an output matching these evaluators." Pure,
   deterministic when mocks are used.

3. AgentTest — invoke a (real or simulated) agent and assert on the
   result: "given this prompt, under this access_profile + mock_profile,
   the agent calls these tools / returns this output." Requires an
   invoker callable when an actual run is needed; capability subset can
   run with no invoker.

All three are storage-only Pydantic models. The runner + evaluators
live in open_agent_compiler/testing/.

Embedding rules:
- AgentDefinition has agent_tests + capability_tests + tool_tests
  (the last for end-to-end tool checks scoped to this agent's context).
- ToolDefinition has tool_tests (the canonical place — runners discover
  them recursively from every tool reachable through any registered
  agent).
- SkillDefinition has skill-level tool_tests that get scoped to the
  skill's tool set.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --------- Evaluator base + discriminated union --------------------------

EvaluatorKind = Literal[
    "equals",
    "substring",
    "regex",
    "json_path",
    "tool_called",
    "tool_not_called",
    "path_order",
    "permission_present",
    "permission_absent",
    "llm_judge",
    "fact_recall",
]


class Evaluator(BaseModel):
    """Base for all evaluators. Subclasses pin `kind` for discrimination."""

    model_config = ConfigDict(frozen=True)

    kind: EvaluatorKind
    name: str = Field(
        default="",
        description="Optional label used in evidence to identify this check.",
    )


class EqualsEvaluator(Evaluator):
    kind: Literal["equals"] = "equals"
    expected: Any
    field: str | None = Field(
        default=None,
        description=(
            "Optional dotted path into a dict-like target; None means"
            " 'compare the whole target'."
        ),
    )


class SubstringEvaluator(Evaluator):
    kind: Literal["substring"] = "substring"
    needle: str
    case_sensitive: bool = True


class RegexEvaluator(Evaluator):
    kind: Literal["regex"] = "regex"
    pattern: str
    flags: int = 0


class JsonPathEvaluator(Evaluator):
    """Evaluate a JSON-Path-like dotted expression against a dict target.

    Limited to dotted keys + integer indices (no jsonpath-ng dependency).
    Example: 'tasks.0.status' selects target['tasks'][0]['status'].
    """

    kind: Literal["json_path"] = "json_path"
    path: str
    expected: Any


class ToolCalledEvaluator(Evaluator):
    """Pass when the AgentTest run's recorded tool_calls include the named tool.

    If with_args_subset is set, every k=v in it must be a subset of the
    actual call args.
    """

    kind: Literal["tool_called"] = "tool_called"
    tool_name: str
    with_args_subset: dict[str, Any] | None = None
    min_count: int = 1


class ToolNotCalledEvaluator(Evaluator):
    kind: Literal["tool_not_called"] = "tool_not_called"
    tool_name: str


class PathOrderEvaluator(Evaluator):
    """Pass when the run's recorded tool/subagent calls contain `steps` as an
    ordered subsequence.

    This is the core check for a multi-step *branch* (an orchestrator that must
    chain several tools / subagents to handle a task): it asserts the chain
    happened AND happened in the right order — not merely that each step
    occurred. Each recorded call name is matched against the trajectory left to
    right; a step matches the first not-yet-consumed call with that name.

    - ordered subsequence by default (other calls may interleave between steps);
    - set `contiguous=True` to require the steps be adjacent (no other calls in
      between), e.g. a strict hand-off pipeline.
    """

    kind: Literal["path_order"] = "path_order"
    steps: tuple[str, ...]
    contiguous: bool = False


class PermissionPresentEvaluator(Evaluator):
    """Pass when a permission key is present + allow-valued in the artifact."""

    kind: Literal["permission_present"] = "permission_present"
    permission_key: str
    bash_pattern: str | None = Field(
        default=None,
        description="Optional bash pattern under permission.bash to check.",
    )


class PermissionAbsentEvaluator(Evaluator):
    """Inverse of PermissionPresentEvaluator — passes when key is absent or deny."""

    kind: Literal["permission_absent"] = "permission_absent"
    permission_key: str
    bash_pattern: str | None = None


class LLMJudgeEvaluator(Evaluator):
    """Ask a configured judge LLM whether the target meets `criteria`.

    The framework provides a default StubJudge for tests; production
    consumers register their own LLM client via the runner.
    """

    kind: Literal["llm_judge"] = "llm_judge"
    criteria: str
    judge_model: str | None = Field(
        default=None,
        description="Optional override; runner default applies when None.",
    )
    pass_threshold: float = 0.5


class FactSpec(BaseModel):
    """One retrievable fact, matched by ANY of its surface forms.

    `any_of` holds acceptable aliases for the same fact ("36mg", "36 mg",
    "thirty-six milligrams") — the fact counts as recalled when at least one
    alias appears in the output.
    """

    model_config = ConfigDict(frozen=True)

    any_of: tuple[str, ...] = Field(min_length=1)
    case_sensitive: bool = False


class FactRecallEvaluator(Evaluator):
    """Graded retrieval check: which expected facts made it into the output?

    score = recalled_facts / len(facts); passed when score >= pass_threshold.
    `forbidden` is the hallucination guard — any forbidden string present in
    the output zeroes the score and fails the check regardless of recall
    (a retrieval answer that fabricates is worse than one that misses).
    An empty `facts` with non-empty `forbidden` is a pure no-hallucination
    probe: score 1.0 unless a forbidden string appears.
    """

    kind: Literal["fact_recall"] = "fact_recall"
    facts: tuple[FactSpec, ...] = ()
    forbidden: tuple[str, ...] = ()
    forbidden_case_sensitive: bool = False
    pass_threshold: float = 1.0


AnyEvaluator = (
    EqualsEvaluator
    | SubstringEvaluator
    | RegexEvaluator
    | JsonPathEvaluator
    | ToolCalledEvaluator
    | ToolNotCalledEvaluator
    | PathOrderEvaluator
    | PermissionPresentEvaluator
    | PermissionAbsentEvaluator
    | LLMJudgeEvaluator
    | FactRecallEvaluator
)


# --------- Test kinds ----------------------------------------------------


class CapabilityTest(BaseModel):
    """Pure introspection test against the compiled permission artifact."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    must_have_tools: tuple[str, ...] = ()
    must_not_have_tools: tuple[str, ...] = ()
    must_have_skills: tuple[str, ...] = ()
    must_not_have_skills: tuple[str, ...] = ()
    must_have_bash_patterns: tuple[str, ...] = ()
    must_not_have_bash_patterns: tuple[str, ...] = ()
    evaluators: tuple[AnyEvaluator, ...] = ()


class ToolTest(BaseModel):
    """Drive a tool's handler (or its mock) under a controlled scenario."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    mock_profile: str | None = Field(
        default=None,
        description=(
            "When set, runner uses this profile's MockResponse for the"
            " tool instead of the real handler. When None, the tool's"
            " own default mock (ToolDefinition.mock) is used if any;"
            " otherwise the real handler runs."
        ),
    )
    access_profile: str | None = Field(
        default=None,
        description="Active AccessProfile name during the run.",
    )
    evaluators: tuple[AnyEvaluator, ...] = ()


class Turn(BaseModel):
    """One conversational turn in a multi-turn AgentTest.

    Each turn carries the user prompt to send, optional per-turn
    expected_tool_calls (shorthand) and evaluators that assert on the
    response *for that turn*. A multi-turn AgentTest fires turns in
    order with the same session/state preserved across them so
    monitoring / memory / DB-write scenarios can be exercised the
    way they actually run.
    """

    model_config = ConfigDict(frozen=True)

    prompt: str = Field(description="User message for this turn.")
    expected_tool_calls: tuple[str, ...] = Field(
        default=(),
        description="Shorthand: ToolCalledEvaluator per name (per turn).",
    )
    evaluators: tuple[AnyEvaluator, ...] = Field(
        default=(),
        description="Evaluators applied to this turn's response.",
    )


class AgentTest(BaseModel):
    """End-to-end agent scenario, single-turn or multi-turn.

    Requires an invoker callable at runtime — the framework cannot
    construct one for you because how an agent actually executes is
    deployment-specific (a real LLM call, a simulator, an OpenCode
    subprocess, etc.). Capability subsets of the test still run without
    an invoker.

    Single-turn: set `prompt` and (optionally) `expected_tool_calls`
    + `evaluators` on the AgentTest itself — same as the original
    shape, fully backwards-compatible.

    Multi-turn: set `turns: tuple[Turn, ...]` and leave `prompt` empty.
    The runner fires each Turn in order against the same session so
    state-accumulating scenarios (DB writes between turns, mocked
    data-stream tick + summarise, monitoring + remember-prior) can be
    asserted realistically.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    prompt: str = Field(
        default="",
        description=(
            "User prompt for the single-turn case. Leave empty when"
            " using `turns` for a multi-turn scenario."
        ),
    )
    turns: tuple[Turn, ...] = Field(
        default=(),
        description=(
            "Sequence of Turn objects for a multi-turn scenario. When"
            " non-empty, the runner threads session state across turns."
            " Mutually exclusive with the top-level `prompt` field."
        ),
    )
    access_profile: str | None = None
    mock_profile: str | None = None
    expected_tool_calls: tuple[str, ...] = Field(
        default=(),
        description=(
            "Convenience shorthand — equivalent to ToolCalledEvaluator"
            " per name. For single-turn, applies to the only turn; for"
            " multi-turn, applies aggregated across all turns. Per-turn"
            " expectations belong on each Turn."
        ),
    )
    evaluators: tuple[AnyEvaluator, ...] = ()
    timeout_s: float = 60.0

    @model_validator(mode="after")
    def _prompt_xor_turns(self) -> "AgentTest":
        if self.prompt and self.turns:
            raise ValueError(
                f"AgentTest {self.name!r} cannot set both `prompt` (single-turn)"
                " and `turns` (multi-turn); pick one."
            )
        if not self.prompt and not self.turns:
            raise ValueError(
                f"AgentTest {self.name!r} must set either `prompt` or `turns`."
            )
        return self

    @property
    def is_multi_turn(self) -> bool:
        return bool(self.turns)

    def all_turns(self) -> tuple[Turn, ...]:
        """Yield Turn objects regardless of single- or multi-turn shape."""
        if self.turns:
            return self.turns
        return (
            Turn(
                prompt=self.prompt,
                expected_tool_calls=self.expected_tool_calls,
                evaluators=self.evaluators,
            ),
        )
