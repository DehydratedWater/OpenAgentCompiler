"""PersonalizationRun — the Phase E keystone (per-client deep-tool-use autoloop).

This ties Phases A–D onto the Phase-0-hardened opencode loop into ONE
per-client, outcome-judged optimisation:

    compile (client overlay + merged surface)
      -> seed probes from ClientSpec.example_tasks
      -> for each probe: run the personalized agent as a FULL opencode session
         (OpencodeRunner) and grade the trajectory with the client rubric
         (OpencodeMutatorClient.judge, routed through opencode — never a raw
         provider API)
      -> joint mutation space (prompt+workflow rewrite AND tool selection /
         sequence / description / rule / format) climbs the score
      -> winners that clear ClientSpec success_criteria promote PER-CLIENT into
         .oac/promoted/<client_id>/  (via run_fleet(client_id=...))

It is re-runnable: call `.run()` again after the client refines their spec in
chat and the loop re-optimises against the new probes/criteria.

The two IO seams — the student session runner and the teacher/judge — are both
injected (`OpencodeRunner` + `OpencodeMutatorClient`, or fakes exposing the same
surface) so the whole run is mockable end-to-end with NO live
opencode/qwen/z.ai/network. Pydantic throughout; provider-guard clean.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.improvement.branch import build_outcome_branch_loop
from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.opencode_eval import flailing_note
from open_agent_compiler.improvement.fleet import FleetResult, ImprovementUnit, agent_unit, run_fleet
from open_agent_compiler.improvement.loop import IterativeLoop
from open_agent_compiler.improvement.mutators import (
    LLMPromptRewriter,
    Mutator,
    MutationContext,
    ToolDescriptionAppendMutator,
    ToolFormatMutator,
    ToolRuleAddMutator,
    ToolSelectionMutator,
    ToolSequenceMutator,
)
from open_agent_compiler.improvement.probe_cache import ProbeCache
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.capability_bundle import ClientCapabilityBundle
from open_agent_compiler.datasource.profile import DatasourceProfile
from open_agent_compiler.personalization.judge import (
    build_client_criterion,
    build_client_rubric,
)
from open_agent_compiler.personalization.probes import seed_probes_from_spec, spec_probe_keys
from open_agent_compiler.personalization.spec import ClientSpec

# A session runner: given (agent_name, prompt) returns an object exposing
# `.final_text()`, `.error`, and `.subagent_dispatch_chain()` — i.e. an
# OpencodeRunResult. Typed loosely so a fake can stand in.
SessionRunner = Callable[..., Any]

# Default judge metric key the client criterion scopes to.
_JUDGE_METRIC_KEY = "score_floor:by_evaluator:llm_judge"


def _result_blocked_details(result: Any) -> list[tuple[str, str]]:
    """Best-effort ``(tool, reason)`` denied attempts off a session result.

    Real `OpencodeRunResult`s expose `blocked_tool_details()`; fakes in tests may
    not — return ``[]`` rather than crash so the evaluator stays mockable.
    """
    fn = getattr(result, "blocked_tool_details", None)
    if callable(fn):
        try:
            return list(fn() or [])
        except Exception:  # noqa: BLE001
            return []
    return []


class PersonalizationRunResult(BaseModel):
    """Outcome of one PersonalizationRun.run()."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    client_id: str
    probe_keys: list[str] = Field(default_factory=list)
    fleet_result: FleetResult | None = None
    promoted: bool = False
    promoted_path: str | None = None
    winner_score: float = 0.0

    def is_promoted(self) -> bool:
        return self.promoted


def build_session_judge_evaluator(
    *,
    spec: ClientSpec,
    probes: ProbeCache,
    probe_keys: list[str],
    runner: SessionRunner,
    judge: Any,
    agent_name_for: Callable[[ComponentVersion], str],
    failures_sink: list[dict[str, Any]] | None = None,
) -> Callable[[ComponentVersion], dict[str, float]]:
    """Evaluator: run each probe as a FULL opencode session, judge the outcome.

    For every spec probe it (1) resolves the candidate to a flat opencode agent
    name (`agent_name_for`), (2) runs the agent as a full session via `runner`
    (an OpencodeRunner), (3) grades the session's final text against the client
    rubric with `judge` (an OpencodeMutatorClient.judge, routed via opencode).
    When the agent produced no prose but DID dispatch sub-agents, the judge is
    shown the trajectory so it grades the actions — not an empty turn.

    Emits `score_floor:by_evaluator:llm_judge` (the worst probe's judge score —
    exactly the key `build_client_criterion` scopes to) plus `pass_rate`,
    `score_floor`, `score_mean`. Errored sessions (discovery/provider failures)
    score 0 and are recorded for the teacher's next rewrite.
    """
    rubric = build_client_rubric(spec)
    pass_threshold = 0.7

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        if failures_sink is not None:
            failures_sink.clear()
        if not probe_keys:
            return {
                _JUDGE_METRIC_KEY: 1.0,
                "score_floor": 1.0, "pass_rate": 1.0, "score_mean": 1.0,
            }
        agent_name = agent_name_for(version)
        scores: list[float] = []
        passes = 0
        for key in probe_keys:
            prompt = probes.get(key)
            result = runner.run(agent_name=agent_name, prompt=prompt)
            err = getattr(result, "error", None)
            # TOOL-DISCIPLINE signal: which forbidden tools the model flailed on
            # (denied by the allow-list). Forward this to the judge AND failures so
            # per-client tuning learns to avoid them — not just score prose alone.
            blocked = _result_blocked_details(result)
            note = flailing_note(blocked, err)
            if err:
                # An errored session is a FAILED run — but label it to the judge as
                # an error (not a silent blank) so the rubric responds, and record
                # the blocked attempts too for the teacher's next rewrite.
                scores.append(0.0)
                if failures_sink is not None:
                    failures_sink.append({
                        "probe": key, "score": 0.0,
                        "error": str(err)[:300], "got_output": "",
                        "blocked_tools": [n for n, _ in blocked],
                        "blocked_attempts": len(blocked),
                        "flailing_note": note,
                    })
                continue
            output = result.final_text()
            chain = [name for name, _ in result.subagent_dispatch_chain()]
            graded = output
            if not str(output or "").strip() and chain:
                graded = (
                    "[agent produced no prose; it acted via: "
                    + " -> ".join(chain) + "]"
                )
            # Append the flailing note so the judge SEES the blocked attempts and
            # lowers the score in proportion (the rubric's tool-discipline clause).
            if note:
                graded = (str(graded or "") + "\n\n" + note).strip()
            verdict = judge.judge(rubric, graded)
            score = float(verdict.get("score", 0.0))
            score = max(0.0, min(1.0, score))
            scores.append(score)
            ok = score >= pass_threshold
            passes += 1 if ok else 0
            # Record blocked attempts even when the judge's other checks pass, so
            # the teacher can still rewrite the prompt to avoid the denied tools.
            if failures_sink is not None and (score < 1.0 or blocked):
                failures_sink.append({
                    "probe": key,
                    "score": round(score, 2),
                    "dispatch_chain": chain[:8],
                    "got_output": str(graded)[:400],
                    "judge_reasoning": str(verdict.get("reasoning", ""))[:250],
                    "blocked_tools": [n for n, _ in blocked],
                    "blocked_attempts": len(blocked),
                })
        floor = min(scores) if scores else 0.0
        mean = sum(scores) / len(scores) if scores else 0.0
        return {
            _JUDGE_METRIC_KEY: floor,
            "score_floor": floor,
            "score_mean": mean,
            "pass_rate": passes / len(probe_keys),
        }

    return evaluator


def build_joint_mutators(
    spec: ClientSpec,
    *,
    teacher: Any = None,
    client_tool_names: tuple[str, ...] = (),
    disablable_tools: tuple[str, ...] = (),
    sequence_tools: tuple[str, ...] = (),
) -> list[Mutator]:
    """Assemble the JOINT mutation space — prompt+workflow AND tool-use.

    The Phase-E "deep tool-use, not prompt tweaks" requirement: the loop mutates
    the FULL `{system_prompt, workflow, enabled tool-set, tool descriptions,
    tool-usage rules, tool format}` surface, not just prose. Returns:

      * `LLMPromptRewriter` — prompt + workflow rewrite. Its guidance is derived
        from the client's goal/preferences/constraints and runs through the
        opencode teacher (when one is on the MutationContext).
      * `ToolDescriptionAppendMutator` / `ToolRuleAddMutator` /
        `ToolFormatMutator` — the Phase-13 tool mutators (clarify a tool's docs,
        add a usage rule, pick the tool format the local model handles best).
      * `ToolSelectionMutator` (disable + enable) and `ToolSequenceMutator`
        (move-earlier) over the client's tools — the new axis that tunes WHICH
        tools and in WHAT order, so the loop optimises tool USAGE for the client.

    `teacher` is unused here directly (it is wired onto the MutationContext so
    the rewriter calls it); it is accepted so callers pass it explicitly.
    """
    guidance = (
        "Rewrite the agent's system prompt (and any multi-step workflow it"
        " describes) so it realises THIS client's workflow using the tools"
        f" available to it. Client goal: {spec.goal.strip()}."
        + (" Preferences: " + "; ".join(spec.preferences) + "." if spec.preferences else "")
        + (" Hard constraints (never violate): " + "; ".join(spec.constraints) + "."
           if spec.constraints else "")
        + " Be explicit and concrete about which tool to use, when, and in what"
        " order. Do not invent unrelated capabilities."
    )
    mutators: list[Mutator] = [
        LLMPromptRewriter(guidance=guidance),
        ToolDescriptionAppendMutator(
            "Use this tool for the client's task when it applies; prefer it over"
            " guessing.",
        ),
        ToolRuleAddMutator(
            "Only call this tool with its documented inputs; do not improvise"
            " arguments.",
        ),
        ToolFormatMutator("json"),
    ]
    # Tool-selection: let the loop drop a tool that hurts and (re)enable the
    # client's own tools onto the allow-list.
    for name in disablable_tools:
        mutators.append(ToolSelectionMutator(name, "disable"))
    for name in client_tool_names:
        mutators.append(ToolSelectionMutator(name, "enable"))
    # Tool-sequence: reshape the order of operations around the client's tools.
    for name in sequence_tools or client_tool_names:
        mutators.append(ToolSequenceMutator(name, direction="earlier"))
    return mutators


class PersonalizationRun(BaseModel):
    """Per-client deep-tool-use autoloop orchestrator (Phase E keystone).

    Construct with the client's id, validated `ClientSpec`, and merged
    `ClientCapabilityBundle`, then call `.run(...)` with the baseline agent
    definition + the injected session runner + teacher/judge. The run seeds
    probes from the spec, builds the client criterion as the promotion gate,
    assembles the joint mutation space, evaluates every candidate as a full
    opencode session graded by the client rubric, and promotes winners into the
    client's bucket via `run_fleet(client_id=...)`.

    Set `multi_step=True` (orchestrator clients) to route evaluation through the
    outcome-judged branch loop with the client rubric as a soft hint.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    client_id: str
    client_spec: ClientSpec
    capability_bundle: ClientCapabilityBundle
    datasource_profiles: tuple[DatasourceProfile, ...] = ()
    target: float = 0.7
    max_rounds: int = 3
    frontier_size: int = 3
    multi_step: bool = False

    def build_criterion(self) -> OptimisationCriterion:
        """The promotion gate — the client's success_criteria as the judge bar.

        Scoped to match the evaluator: multi_step routes through the outcome
        branch evaluator (bare `score_floor`), single-shot through the session
        judge (`score_floor:by_evaluator:llm_judge`).
        """
        return build_client_criterion(
            self.client_spec, target=self.target, multi_step=self.multi_step
        )

    def seed_probes(self, oac_dir: Path) -> ProbeCache:
        """Seed the ProbeCache from the client's example tasks (Phase D)."""
        return seed_probes_from_spec(
            self.client_spec, oac_dir / self.client_id / "probes.json",
        )

    def joint_mutators(self, *, teacher: Any = None) -> list[Mutator]:
        """The joint (prompt+workflow + tool-use) mutation space for this client."""
        client_tools = self.capability_bundle.client_tool_names()
        return build_joint_mutators(
            self.client_spec,
            teacher=teacher,
            client_tool_names=client_tools,
        )

    def run(
        self,
        *,
        baseline_definition: dict[str, Any] | ComponentVersion,
        runner: SessionRunner,
        judge: Any,
        teacher: Any = None,
        agent_name_for: Callable[[ComponentVersion], str],
        project_root: Path,
        oac_dir: Path | None = None,
        snapshots_dir: Path | None = None,
        component_id: str | None = None,
        branch_tests: list[Any] | None = None,
        branch_invoker_factory: Callable[[dict[str, Any]], Any] | None = None,
    ) -> PersonalizationRunResult:
        """Run the per-client loop and promote winners into the client bucket.

        - `baseline_definition`: the personalized agent's AgentDefinition dump
          (or a ComponentVersion). The system_prompt already carries the client
          overlay from `compile_personalized`.
        - `runner`: an `OpencodeRunner` (or fake) — the FULL-session student.
        - `judge` / `teacher`: an `OpencodeMutatorClient` (or fakes). The judge
          grades the trajectory; the teacher (on the MutationContext) rewrites
          the prompt from the recorded failures. Both route through opencode.
        - `agent_name_for`: resolves a candidate ComponentVersion to the flat
          opencode agent name installed in `project_root` (Phase-0 helper).
        - `project_root` + `client_id` send promotions to
          `.oac/promoted/<client_id>/`.

        Returns a `PersonalizationRunResult`. Re-runnable on spec change.
        """
        self.client_spec.require_usable()
        oac_dir = oac_dir or (project_root / ".oac")
        criterion = self.build_criterion()
        component_id = component_id or _component_id_of(baseline_definition)

        probes = self.seed_probes(oac_dir)
        keys = spec_probe_keys(self.client_spec)

        failures: list[dict[str, Any]] = []
        mutators = self.joint_mutators(teacher=teacher)
        mutation_ctx = MutationContext(
            criterion=criterion, llm=teacher, failures=failures,
        )

        if self.multi_step:
            if branch_tests is None or branch_invoker_factory is None:
                raise ValueError(
                    "multi_step=True requires branch_tests + branch_invoker_factory"
                )
            loop = build_outcome_branch_loop(
                entry_agent=component_id,
                entry_definition=_definition_of(baseline_definition),
                tests=branch_tests,
                invoker_factory=branch_invoker_factory,
                mutators=mutators,
                criterion=criterion,
                judge=judge,
                failures_sink=failures,
                max_rounds=self.max_rounds,
                frontier_size=self.frontier_size,
                mutation_context=mutation_ctx,
                pass_threshold=self.target,
            )
            unit_id = loop.baseline.component_id
        else:
            baseline = _as_version(baseline_definition, component_id)
            evaluator = build_session_judge_evaluator(
                spec=self.client_spec,
                probes=probes,
                probe_keys=keys,
                runner=runner,
                judge=judge,
                agent_name_for=agent_name_for,
                failures_sink=failures,
            )
            loop = IterativeLoop(
                baseline=baseline,
                mutators=mutators,
                criterion=criterion,
                evaluator=evaluator,
                max_rounds=self.max_rounds,
                frontier_size=self.frontier_size,
                mutation_context=mutation_ctx,
            )
            unit_id = component_id

        unit: ImprovementUnit = agent_unit(unit_id, loop)
        fleet = run_fleet(
            [unit],
            snapshots_dir=snapshots_dir,
            project_root=project_root,
            promote_threshold=self.target,
            client_id=self.client_id,
            run_label=f"personalize:{self.client_id}",
        )
        outcome = fleet.by_id(unit_id)
        return PersonalizationRunResult(
            client_id=self.client_id,
            probe_keys=keys,
            fleet_result=fleet,
            promoted=bool(outcome and outcome.promoted),
            promoted_path=outcome.promoted_path if outcome else None,
            winner_score=outcome.winner_score if outcome else 0.0,
        )


# ---- small helpers ---------------------------------------------------------


def _definition_of(baseline: dict[str, Any] | ComponentVersion) -> dict[str, Any]:
    if isinstance(baseline, ComponentVersion):
        return dict(baseline.definition)
    return dict(baseline)


def _component_id_of(baseline: dict[str, Any] | ComponentVersion) -> str:
    if isinstance(baseline, ComponentVersion):
        return baseline.component_id
    header = baseline.get("header") if isinstance(baseline, dict) else None
    if isinstance(header, dict) and header.get("agent_id"):
        return str(header["agent_id"])
    if isinstance(baseline, dict) and baseline.get("name"):
        return str(baseline["name"])
    return "personalized-agent"


def _as_version(
    baseline: dict[str, Any] | ComponentVersion, component_id: str,
) -> ComponentVersion:
    if isinstance(baseline, ComponentVersion):
        return baseline
    return ComponentVersion.of(
        component_id=component_id, kind="agent", definition=baseline,
    )


__all__ = [
    "SessionRunner",
    "PersonalizationRunResult",
    "build_session_judge_evaluator",
    "build_joint_mutators",
    "PersonalizationRun",
]
