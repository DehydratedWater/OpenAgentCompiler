"""Workflow DAG spec — slow multi-step orchestration as plain, mutable data.

`WorkflowStepDefinition` (open_agent_compiler/model/core/workflow_model.py) is prompt-hints
for an LLM: the *model* reads the steps and decides what to do. Consumers
that need deterministic multi-step pipelines (cron jobs, ingest chains,
study-mode flows) have been hand-rolling their own orchestration around it.

This module makes such workflows first-class AND autoloop-optimizable. The
trick is the same one `open_agent_compiler.improvement.autoresearch` relies on: the spec is
plain JSON-able Pydantic data. Step runners are referenced **by name** and
resolved only at run time, so a `WorkflowSpec.model_dump()` can be stored as
a `ComponentVersion` definition, stepped by the field mutators
(`open_agent_compiler.improvement.mutators.fields` — "steps.0.params.threshold"), rebuilt
via `model_validate`, and re-run against probes. Topology (routes, gates,
retry budgets) and step params are all knobs the improvement loop can turn.

Spec semantics (executed by `open_agent_compiler.workflow.executor`):

- a step's :class:`Gate` (reused from the workflow model — same shape the
  opencode prompt renders) checks ``state[check.variable]`` *stringified*
  against ``check.value`` under all/any logic; a failed gate skips the step;
- after a successful step, :class:`WorkflowRoute`\\ s are evaluated in order
  against the workflow state (first match wins), falling back to ``next``;
- runner return values: ``dict`` merges into state, ``None`` is silent, and
  any non-None return is also stored at ``state[f"{step_id}.output"]`` so
  routes can match on it.

State lookups (``WorkflowContext.get``, route ``when``, gate variables) are
dotted paths — but an exact flat key always wins, because step outputs live
under the literal key ``"<step_id>.output"``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from open_agent_compiler.interactive.events import EventEmitter, EventSink
from open_agent_compiler.model.core.workflow_model import Gate

__all__ = [
    "WorkflowRoute",
    "WorkflowStepSpec",
    "WorkflowSpec",
    "WorkflowContext",
    "StepRunner",
    "get_path",
    "gate_passes",
    "MISSING",
]


# Sentinel for "path not present" — distinguishes a stored None from absence.
MISSING: Any = object()


def _lookup(container: Any, path: str) -> Any:
    """Resolve ``path`` inside ``container``; :data:`MISSING` when absent.

    Exact flat keys win over dotted descent (step outputs are stored under
    the literal key ``"<step_id>.output"``). Otherwise the longest flat
    prefix present in a dict is consumed before descending; digit segments
    index into lists.
    """
    if not path:
        return container
    if isinstance(container, dict):
        if path in container:
            return container[path]
        segments = path.split(".")
        for i in range(len(segments) - 1, 0, -1):
            prefix = ".".join(segments[:i])
            if prefix in container:
                found = _lookup(container[prefix], ".".join(segments[i:]))
                if found is not MISSING:
                    return found
        return MISSING
    if isinstance(container, list):
        head, _, rest = path.partition(".")
        if head.isdigit() and int(head) < len(container):
            return _lookup(container[int(head)], rest)
        return MISSING
    return MISSING


def get_path(container: Any, path: str, default: Any = None) -> Any:
    """Dotted-path lookup with a default. See :func:`_lookup` for rules."""
    value = _lookup(container, path)
    return default if value is MISSING else value


def gate_passes(gate: Gate, state: dict[str, Any]) -> bool:
    """Runtime Gate semantics: ``str(state[variable]) == value`` per check,
    combined under the gate's all/any logic. A missing variable fails its
    check (it cannot equal anything)."""
    outcomes = []
    for check in gate.checks:
        value = _lookup(state, check.variable)
        outcomes.append(value is not MISSING and str(value) == check.value)
    return all(outcomes) if gate.logic == "all" else any(outcomes)


class WorkflowRoute(BaseModel):
    """After a step succeeds: if ``state[when] == equals``, jump to ``goto``."""

    model_config = ConfigDict(frozen=True)

    when: str
    equals: Any = None
    goto: str


class WorkflowStepSpec(BaseModel):
    """One node in the DAG. ``runner`` is a *name* resolved at run time, so
    the spec stays JSON-able (and therefore mutable by the improvement loop).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    runner: str
    params: dict[str, Any] = Field(default_factory=dict)
    gate: Gate | None = None
    routes: tuple[WorkflowRoute, ...] = ()
    next: str | None = Field(
        default=None,
        description="Default successor when no route matches. None = terminal.",
    )
    retries: int = Field(default=0, ge=0)
    on_error: str | None = Field(
        default=None,
        description="Step to jump to when retries are exhausted, instead of failing the run.",
    )


class WorkflowSpec(BaseModel):
    """The whole DAG. Validates referential integrity up front so a mutated
    candidate with a dangling edge dies at ``model_validate`` time, not
    mid-run."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    start: str
    steps: tuple[WorkflowStepSpec, ...]

    @model_validator(mode="after")
    def _graph_is_consistent(self) -> "WorkflowSpec":
        ids = [s.id for s in self.steps]
        seen: set[str] = set()
        dupes = sorted({i for i in ids if i in seen or seen.add(i)})
        if dupes:
            raise ValueError(f"duplicate step ids: {dupes}")
        known = set(ids)
        if self.start not in known:
            raise ValueError(f"start step {self.start!r} is not a defined step id")
        for step in self.steps:
            refs = [("next", step.next), ("on_error", step.on_error)]
            refs += [(f"routes[{i}].goto", r.goto) for i, r in enumerate(step.routes)]
            for label, ref in refs:
                if ref is not None and ref not in known:
                    raise ValueError(
                        f"step {step.id!r}: {label} references unknown step {ref!r}"
                    )
        return self

    def step(self, step_id: str) -> WorkflowStepSpec:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)


class WorkflowContext:
    """What a step runner sees: the shared mutable state plus the run's
    emitter (so a runner can push its own mid-step progress/messages).

    Deliberately a plain class, not a model — it carries live objects and is
    never serialized; the *spec* is the data, the context is the run.
    """

    def __init__(
        self,
        state: dict[str, Any] | None = None,
        emitter: EventEmitter | EventSink | None = None,
    ) -> None:
        self.state: dict[str, Any] = state if state is not None else {}
        if isinstance(emitter, EventEmitter):
            self.emitter = emitter
        else:
            self.emitter = EventEmitter(emitter)

    def get(self, path: str, default: Any = None) -> Any:
        """Dotted-path read from the workflow state."""
        return get_path(self.state, path, default)


# A step's behaviour: (context, params) -> result. May be sync or async.
# Return semantics: dict merges into state; None is silent; any non-None
# value is also stored at state[f"{step_id}.output"].
StepRunner = Callable[[WorkflowContext, dict[str, Any]], "Awaitable[Any] | Any"]
