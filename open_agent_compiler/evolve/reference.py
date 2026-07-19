"""Reference-harness comparison — evolve against a stronger model's sessions.

Commit replay grounds the harness in history; reference comparison
grounds it in a TEACHER: run example sessions once with the same
harness powered by a stronger model (e.g. glm-5.2), persist those
outputs as the reference, then score the evolving (cheaper/faster)
harness by how close its outputs come — classic teacher/student
distillation, applied to the whole harness instead of one model.

    tasks = [ReferenceTask(task_id="add-endpoint", prompt="Add …"), ...]

    # once, expensive — the teacher run
    refs = generate_references(
        workspace, tasks,
        registry=build_harness_registry(profile, model_name=STRONG_MODEL),
        dialect="opencode", agent_name="implementer",
        out_path=workspace / ".oac-harness" / "reference_outputs.json",
    )

    # in the loop, per candidate — the student scored against the teacher
    evaluator = build_reference_evaluator(
        workspace, tasks, refs,
        registry_factory=..., dialect="opencode", agent_name="implementer",
    )

Scoring is deterministic text similarity (SequenceMatcher) with the
standard metric names; add an `llm_judge` probe layer on top when you
want "is the student's answer as good as the teacher's" judged
qualitatively rather than textually.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict

from open_agent_compiler.compiler.script import CompileScript
from open_agent_compiler.improvement.harness_eval import HarnessRunner, get_runner
from open_agent_compiler.improvement.loop import Evaluator
from open_agent_compiler.improvement.version import ComponentVersion

_MAX_CHARS = 20_000


class ReferenceTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    prompt: str


def output_similarity(reference: str, candidate: str) -> float:
    if not reference.strip() and not candidate.strip():
        return 1.0
    if not reference.strip() or not candidate.strip():
        return 0.0
    return difflib.SequenceMatcher(
        None, reference[:_MAX_CHARS], candidate[:_MAX_CHARS],
    ).ratio()


def generate_references(
    workspace: Path,
    tasks: list[ReferenceTask],
    *,
    registry: Any,
    dialect: str = "opencode",
    config: str = "harness",
    agent_name: str = "implementer",
    runner: HarnessRunner | None = None,
    timeout_s: float | None = 600.0,
    out_path: Path | None = None,
) -> dict[str, str]:
    """Run every task through the TEACHER harness once; return/persist outputs.

    `registry` is the strong-model registry (e.g.
    `build_harness_registry(profile, model_name="zai-coding-plan/glm-5.2")`).
    A task whose teacher run errors is skipped (recorded as absent) —
    a broken reference must not become a target.
    """
    CompileScript(
        target=workspace, factory=lambda: registry, config=config,
        dialect=dialect,
    ).run()
    live_runner = runner or get_runner(dialect, workspace)
    references: dict[str, str] = {}
    for task in tasks:
        result = live_runner.run(
            agent_name=agent_name, prompt=task.prompt, timeout_s=timeout_s,
        )
        if result.error:
            continue
        references[task.task_id] = result.final_text()
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(references, indent=2) + "\n")
    return references


def load_references(path: Path) -> dict[str, str]:
    return json.loads(path.read_text())


def build_reference_evaluator(
    workspace: Path,
    tasks: list[ReferenceTask],
    references: dict[str, str],
    *,
    registry_factory: Callable[[dict[str, Any]], Any],
    dialect: str = "opencode",
    config: str = "harness",
    agent_name: str = "implementer",
    runner: HarnessRunner | None = None,
    timeout_s: float | None = 600.0,
    gap_sink: dict[str, Any] | None = None,
) -> Evaluator:
    """Score candidates by similarity to the teacher's reference outputs.

    Standard metric names (`pass_rate` / `score_floor` / `score_mean` /
    `score_floor:by_name:<task>`); tasks without a stored reference are
    skipped. A failed student run scores 0 for that task.

    `gap_sink` (a plain dict you own) is updated after every evaluation
    with the WORST task's teacher/student excerpts — the evidence an
    LLM prompt-rewriter needs to adapt the prompt toward closing the
    gap. Wire it by rendering the sink into the rewriter's guidance:

        gaps: dict = {}
        evaluator = build_reference_evaluator(..., gap_sink=gaps)
        rewriter = LLMPromptRewriter(guidance=lambda: ...)  # or a custom
        # Mutator subclass that reads `gaps` at mutate time — the sink
        # holds the previous round's worst gap when the next round's
        # mutations are proposed.
    """
    scored_tasks = [t for t in tasks if t.task_id in references]

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        registry = registry_factory(version.definition_copy())
        CompileScript(
            target=workspace, factory=lambda: registry, config=config,
            dialect=dialect,
        ).run()
        live_runner = runner or get_runner(dialect, workspace)

        scores: list[float] = []
        metrics: dict[str, float] = {}
        outputs: dict[str, str] = {}
        for task in scored_tasks:
            try:
                result = live_runner.run(
                    agent_name=agent_name, prompt=task.prompt,
                    timeout_s=timeout_s,
                )
                student = "" if result.error else result.final_text()
                score = output_similarity(references[task.task_id], student)
            except Exception:
                student, score = "", 0.0
            outputs[task.task_id] = student
            scores.append(score)
            metrics[f"score_floor:by_name:{task.task_id}"] = score

        if scores:
            metrics["pass_rate"] = sum(1 for s in scores if s > 0) / len(scores)
            metrics["score_floor"] = min(scores)
            metrics["score_mean"] = sum(scores) / len(scores)
            if gap_sink is not None:
                worst_i = min(range(len(scores)), key=lambda i: scores[i])
                worst = scored_tasks[worst_i]
                gap_sink.update({
                    "task_id": worst.task_id,
                    "prompt": worst.prompt,
                    "score": scores[worst_i],
                    "teacher_excerpt": references[worst.task_id][:2000],
                    "student_excerpt": outputs[worst.task_id][:2000],
                })
        return metrics

    return evaluator
