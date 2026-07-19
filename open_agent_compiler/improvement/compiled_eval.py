"""Turnkey compiled-target evaluator — compile → run → judge, one call.

`run_per_target_loops` needs an evaluator per target; for compiled
harnesses that meant hand-wiring "merge the candidate into a registry,
compile it into a build dir, invoke the harness, score the output"
every time. `build_compiled_evaluator` packages that chain, mirroring
`interactive_eval.build_interactive_evaluator`'s probe shape so the
same probes (and the same `llm_judge` wiring) score both tiers:

    def registry_factory(defn: dict) -> AgentRegistry:
        # merge the mutated fields into YOUR registry — same contract
        # as branch.py's invoker_factory / interactive_eval's spec_factory
        return make_registry(system_prompt=defn["system_prompt"])

    evaluator = build_compiled_evaluator(
        probes=[Probe(probe_id="smoke", payload="summarize X",
                      evaluators=(LLMJudgeEvaluator(criteria="concise"),))],
        registry_factory=registry_factory,
        target=OptimizationTarget(harness="pi", model_class="fast"),
        build_dir=Path("eval_build/pi_fast"),
        config="prod",
        agent_name="summarizer",
        judge=my_judge,
    )

Each candidate is compiled with the target's dialect into `build_dir`
(overwriting the previous candidate's tree), every probe runs through
the harness runner (`get_runner(target.harness, build_dir)` unless one
is injected), and outcomes are scored by the standard dispatcher —
metric names (`pass_rate` / `score_floor` / `score_mean` /
`score_floor:by_name:<probe>`) match branch / autoresearch /
interactive, so criteria, gates, charts and per-target promotion work
unchanged. A harness failure (`result.error`) fails the probe instead
of letting a judge grade partial output.

Give each target its own `build_dir` when loops run in parallel
(fleet): the directory is the candidate's workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from open_agent_compiler.compiler.compile import build
from open_agent_compiler.improvement.autoresearch import (
    Probe,
    ProbeOutcome,
    metrics_from_results,
    run_probes,
)
from open_agent_compiler.improvement.harness_eval import HarnessRunner, get_runner
from open_agent_compiler.improvement.loop import Evaluator
from open_agent_compiler.improvement.target_loop import OptimizationTarget
from open_agent_compiler.improvement.version import ComponentVersion

# Candidate definition dict → the registry to compile. The consumer owns
# the merge; the factory receives a deep copy so mutation is safe.
RegistryFactory = Callable[[dict[str, Any]], Any]


def compiled_probe_executable(
    runner: HarnessRunner,
    agent_name: str,
    *,
    timeout_s: float | None = None,
    fail_on_error: bool = True,
) -> Callable[[Any], ProbeOutcome]:
    """A ProbeExecutable that runs prompts through one compiled agent.

    The probe payload is the prompt (a string, or a dict with a
    "prompt" key when a probe wants to carry extras for its judge).
    """

    def _execute(payload: Any) -> ProbeOutcome:
        prompt = payload.get("prompt") if isinstance(payload, dict) else str(payload)
        result = runner.run(
            agent_name=agent_name, prompt=str(prompt), timeout_s=timeout_s,
        )
        if fail_on_error and result.error:
            raise RuntimeError(f"harness run failed: {result.error}")
        return ProbeOutcome(
            output=result.final_text(),
            extras={"error": result.error, "harness": getattr(runner, "harness_name", "?")},
        )

    return _execute


def build_compiled_evaluator(
    probes: list[Probe],
    *,
    registry_factory: RegistryFactory,
    target: OptimizationTarget,
    build_dir: Path,
    config: str,
    agent_name: str,
    runner: HarnessRunner | None = None,
    judge: Any = None,
    timeout_s: float | None = None,
    native_tools: bool = False,
) -> Evaluator:
    """An IterativeLoop evaluator that compiles each candidate for
    `target.harness` and scores it by live harness runs.

    `target.harness` must be a registered compile dialect (opencode /
    claude / pi / codex / your own); for the in-process tier use
    `interactive_eval.build_interactive_evaluator` instead.
    """

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        registry = registry_factory(version.definition_copy())
        build_dir.mkdir(parents=True, exist_ok=True)
        build(
            build_dir, registry, config,
            dialect=target.harness,
            options={"native_tools": native_tools},
        )
        live_runner = runner or get_runner(target.harness, build_dir)
        executable = compiled_probe_executable(
            live_runner, agent_name, timeout_s=timeout_s,
        )
        return metrics_from_results(run_probes(probes, executable, judge=judge))

    return evaluator
