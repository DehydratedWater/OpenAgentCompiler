"""Workflow DAG executor — run a `WorkflowSpec` against named runners.

The spec (`open_agent_compiler.workflow.dag`) is inert data; this module is the engine. The
two are split so the *spec* can travel through the improvement loop (stored,
mutated, revalidated) while the *runners* — the actual side-effecting
callables — are bound only at execution time, per environment.

Execution contract (see `WorkflowSpec` docs for spec semantics):

- one cursor walks the graph from ``start``; a ``max_steps`` guard turns
  accidental cycles into a ``"halted"`` result instead of a hang;
- a failed gate records ``gate_skipped`` and advances to ``next`` (routes
  are NOT evaluated for a skipped step — they may depend on its output);
- each attempt (up to ``retries + 1``) is its own `StepRunRecord`, so the
  result is a full audit trail the improvement loop's evaluators (and
  humans) can inspect; an unknown runner name is just another step error,
  so ``retries``/``on_error`` apply uniformly;
- progress is pushed through the dependency-light `EventEmitter`
  (open_agent_compiler/interactive/events.py) under ``source=f"workflow:{workflow_id}"`` —
  the same stream a chat UI already consumes for tools/subagents.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.interactive.events import EventEmitter, EventSink
from open_agent_compiler.workflow.dag import (
    MISSING,
    StepRunner,
    WorkflowContext,
    WorkflowSpec,
    WorkflowStepSpec,
    gate_passes,
    get_path,
)

__all__ = [
    "StepRunRecord",
    "WorkflowResult",
    "run_workflow",
    "run_workflow_sync",
]


class StepRunRecord(BaseModel):
    """One attempt at one step — ok, error, or skipped by its gate."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_id: str
    attempt: int
    status: Literal["ok", "error", "gate_skipped"]
    output: Any = None
    error: str | None = None


class WorkflowResult(BaseModel):
    """The full run: final state plus the per-attempt audit trail.

    ``halted`` means the ``max_steps`` guard fired (e.g. a route cycle) —
    distinct from ``failed`` so an optimizer can penalize the two
    differently.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    workflow_id: str
    status: Literal["completed", "failed", "halted"]
    state: dict[str, Any]
    records: list[StepRunRecord] = Field(default_factory=list)
    error: str | None = None


async def _execute_with_retries(
    step: WorkflowStepSpec,
    runner: StepRunner | None,
    ctx: WorkflowContext,
    records: list[StepRunRecord],
    emitter: EventEmitter,
) -> tuple[bool, Any, str | None]:
    """Run one step up to ``retries + 1`` times. Returns (ok, output, error)."""
    error: str | None = None
    for attempt in range(1, step.retries + 2):
        try:
            if runner is None:
                raise LookupError(f"unknown runner {step.runner!r}")
            result = runner(ctx, dict(step.params))
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 — a step failure is data, not a crash
            error = f"{type(exc).__name__}: {exc}"
            records.append(
                StepRunRecord(
                    step_id=step.id, attempt=attempt, status="error", error=error,
                )
            )
            emitter.tool_error(error, step=step.id, attempt=attempt)
            continue
        records.append(
            StepRunRecord(
                step_id=step.id, attempt=attempt, status="ok", output=result,
            )
        )
        return True, result, None
    return False, None, error


def _pick_successor(step: WorkflowStepSpec, state: dict[str, Any]) -> str | None:
    """First matching route wins; otherwise the default ``next``."""
    for route in step.routes:
        value = get_path(state, route.when, MISSING)
        if value is not MISSING and value == route.equals:
            return route.goto
    return step.next


async def run_workflow(
    spec: WorkflowSpec,
    runners: Mapping[str, StepRunner],
    *,
    initial_state: dict[str, Any] | None = None,
    sink: EventSink | Any = None,
    max_steps: int = 100,
) -> WorkflowResult:
    """Walk the DAG from ``spec.start`` until a terminal step, a failure
    without ``on_error``, or the ``max_steps`` guard."""
    state: dict[str, Any] = dict(initial_state or {})
    emitter = EventEmitter(sink, source=f"workflow:{spec.workflow_id}")
    ctx = WorkflowContext(state, emitter)
    steps_by_id = {s.id: s for s in spec.steps}
    records: list[StepRunRecord] = []
    cursor: str | None = spec.start
    visited = 0

    while cursor is not None:
        if visited >= max_steps:
            return WorkflowResult(
                workflow_id=spec.workflow_id,
                status="halted",
                state=state,
                records=records,
                error=f"max_steps={max_steps} reached at step {cursor!r} (cycle?)",
            )
        step = steps_by_id[cursor]
        visited += 1
        emitter.progress(
            f"step {step.id} start", current=visited, step=step.id, phase="start",
        )

        if step.gate is not None and not gate_passes(step.gate, state):
            records.append(
                StepRunRecord(step_id=step.id, attempt=0, status="gate_skipped")
            )
            emitter.progress(
                f"step {step.id} gate_skipped",
                current=visited, step=step.id, phase="end", status="gate_skipped",
            )
            cursor = step.next  # routes are NOT evaluated on a skipped step
            continue

        ok, output, error = await _execute_with_retries(
            step, runners.get(step.runner), ctx, records, emitter,
        )
        if not ok:
            if step.on_error is not None:
                emitter.progress(
                    f"step {step.id} error -> {step.on_error}",
                    current=visited, step=step.id, phase="end", status="error",
                )
                cursor = step.on_error
                continue
            return WorkflowResult(
                workflow_id=spec.workflow_id,
                status="failed",
                state=state,
                records=records,
                error=f"step {step.id!r} failed after {step.retries + 1} attempt(s): {error}",
            )

        if output is not None:
            if isinstance(output, dict):
                state.update(output)
            state[f"{step.id}.output"] = output
        emitter.progress(
            f"step {step.id} ok",
            current=visited, step=step.id, phase="end", status="ok",
        )
        cursor = _pick_successor(step, state)

    return WorkflowResult(
        workflow_id=spec.workflow_id,
        status="completed",
        state=state,
        records=records,
    )


def run_workflow_sync(
    spec: WorkflowSpec,
    runners: Mapping[str, StepRunner],
    *,
    initial_state: dict[str, Any] | None = None,
    sink: EventSink | Any = None,
    max_steps: int = 100,
) -> WorkflowResult:
    """Blocking wrapper for sync callers (CLI, autoresearch executables)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "run_workflow_sync() called from inside a running event loop; "
            "use `await run_workflow(...)` instead.",
        )
    return asyncio.run(
        run_workflow(
            spec,
            runners,
            initial_state=initial_state,
            sink=sink,
            max_steps=max_steps,
        )
    )
