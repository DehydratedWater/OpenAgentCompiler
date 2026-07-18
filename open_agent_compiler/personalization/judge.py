"""Spec-seeded judge — score candidates on what the CLIENT said 'good' means.

The autoloop grades candidates with an LLM judge against a rubric. Phase D makes
that rubric the client's OWN `ClientSpec.success_criteria` (plus goal/constraints
as context), so a promoted candidate is the one the client would call good — not
one that matches a generic, framework-authored notion of quality.

Two reused builders, parameterised by the spec:

  * `build_client_criterion(spec)` → an `OptimisationCriterion` (the loop's
    promotion gate) requiring the llm-judge `score_floor` to clear a threshold.
  * `build_client_judge_test(spec, prompt=...)` → an `AgentTest` carrying a single
    `LLMJudgeEvaluator` whose `criteria` string is the rubric composed from the
    spec. Combined with a spec PROBE prompt it is the graded test the loop runs.

`build_client_rubric(spec)` exposes the rubric string on its own so the same
wording can seed a branch-outcome judge or a probe's in-band success note.

Pure data + string composition; no IO. The judge that consumes the test is the
opencode-routed teacher (`OpencodeMutatorClient.judge`) — never a raw provider.
"""

from __future__ import annotations

from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.model.core.test_model import AgentTest, LLMJudgeEvaluator
from open_agent_compiler.personalization.spec import ClientSpec

# The llm-judge metric the criterion scopes to. The branch/loop evaluators emit
# `score_floor:by_evaluator:llm_judge` for judge-scored tests; scoping by
# evaluator keeps the client criterion measuring exactly the judge signal.
JUDGE_EVALUATOR_KIND = "llm_judge"


def build_client_rubric(spec: ClientSpec) -> str:
    """Compose the LLM-judge rubric text from a client's success criteria.

    Weaves the goal (context), the explicit success_criteria (the scored bar),
    and any hard constraints (violations cap the score) into one instruction.
    Requires ≥1 success_criterion (a usable spec).
    """
    if not spec.success_criteria:
        raise ValueError(
            "ClientSpec has no success_criteria — cannot build a judge rubric"
        )
    criteria_lines = "\n".join(f"  - {c}" for c in spec.success_criteria)
    rubric = (
        f"The agent's job for this client is: {spec.goal.strip()}\n"
        "Score 0.0-1.0 how well the RESPONSE meets the CLIENT'S OWN definition of"
        " a good result, which is ALL of:\n"
        f"{criteria_lines}\n"
        "1.0 = fully satisfies every criterion above; 0.0 = ignores them, refuses,"
        " stalls, or returns nothing usable. Reward a complete, on-task result;"
        " penalise off-task rambling or tool-mechanics leaking into the answer.\n"
        "TOOL DISCIPLINE: if the response carries a 'TOOL DISCIPLINE' note that the"
        " agent made DENIED/blocked tool attempts (forbidden by its allow-list) or"
        " that the session ERRORED, lower the score in proportion to the number of"
        " blocked attempts, and treat an errored session as a failed run (near 0)."
    )
    if spec.constraints:
        constraint_lines = "\n".join(f"  - {c}" for c in spec.constraints)
        rubric += (
            "\nThe client also set HARD CONSTRAINTS; a response that violates any"
            f" of these cannot score above 0.3:\n{constraint_lines}"
        )
    return rubric


def build_client_criterion(
    spec: ClientSpec,
    *,
    target: float = 0.7,
    name: str = "client-success",
    multi_step: bool = False,
) -> OptimisationCriterion:
    """Build the loop's promotion gate from a client's success criteria.

    A single `score_floor` Criterion: the candidate's judge score must clear
    `target`. Requires a usable rubric (≥1 success_criterion). The criterion's
    description carries the composed rubric so it is self-documenting in
    snapshots/reports.

    The criterion's metric scope MUST match the evaluator that will run:
    - single-shot (`multi_step=False`): the session-judge evaluator emits
      `score_floor:by_evaluator:llm_judge`, so scope by that evaluator;
    - multi-step (`multi_step=True`): `build_outcome_branch_evaluator` emits a
      BARE `score_floor` (no per-evaluator scoping), so scope must be "any" or the
      gate never matches → neutral 0.5 → an orchestrator could never promote.
    """
    rubric = build_client_rubric(spec)  # validates success_criteria present
    if multi_step:
        criterion = Criterion(
            name=name,
            kind="score_floor",
            target=target,
            scope="any",
            hard=False,
        )
    else:
        criterion = Criterion(
            name=name,
            kind="score_floor",
            target=target,
            scope="by_evaluator",
            scope_value=JUDGE_EVALUATOR_KIND,
            hard=False,
        )
    return OptimisationCriterion(
        name=name,
        aggregation="weighted",
        criteria=(criterion,),
        description=rubric,
    )


def build_client_judge_test(
    spec: ClientSpec,
    *,
    prompt: str,
    name: str = "client-success",
    pass_threshold: float = 0.7,
    judge_model: str | None = None,
) -> AgentTest:
    """Build a graded `AgentTest` that scores `prompt` against the client rubric.

    `prompt` is typically a spec example-task probe (see `seed_probes_from_spec`).
    The returned test carries one `LLMJudgeEvaluator` whose `criteria` is the
    composed client rubric, so the configured (opencode-routed) judge grades the
    candidate's response by the client's standard.
    """
    if not prompt or not prompt.strip():
        raise ValueError("build_client_judge_test requires a non-empty prompt")
    rubric = build_client_rubric(spec)
    return AgentTest(
        name=name,
        prompt=prompt,
        evaluators=(
            LLMJudgeEvaluator(
                name=name,
                criteria=rubric,
                pass_threshold=pass_threshold,
                judge_model=judge_model,
            ),
        ),
    )


__all__ = [
    "JUDGE_EVALUATOR_KIND",
    "build_client_rubric",
    "build_client_criterion",
    "build_client_judge_test",
]
