"""Workflow DAG runtime — deterministic multi-step orchestration as data.

Splits cleanly in two, on purpose:

- `open_agent_compiler.workflow.dag` — the **spec**: frozen, JSON-able Pydantic models with
  step runners referenced by name. Because the spec round-trips through
  ``model_dump()`` / ``model_validate()``, it can be stored as a
  `ComponentVersion` definition and tuned by the autoresearch loop
  (`open_agent_compiler.improvement.autoresearch` + `open_agent_compiler.improvement.mutators.fields`).
- `open_agent_compiler.workflow.executor` — the **engine**: binds names to live runners at
  run time, walks the graph with gates/routes/retries, and streams progress
  through the interactive `EventEmitter`.
"""

from open_agent_compiler.workflow.dag import (
    MISSING,
    StepRunner,
    WorkflowContext,
    WorkflowRoute,
    WorkflowSpec,
    WorkflowStepSpec,
    gate_passes,
    get_path,
)
from open_agent_compiler.workflow.executor import (
    StepRunRecord,
    WorkflowResult,
    run_workflow,
    run_workflow_sync,
)

__all__ = [
    # spec
    "WorkflowRoute",
    "WorkflowStepSpec",
    "WorkflowSpec",
    "WorkflowContext",
    "StepRunner",
    "get_path",
    "gate_passes",
    "MISSING",
    # engine
    "StepRunRecord",
    "WorkflowResult",
    "run_workflow",
    "run_workflow_sync",
]
