"""Workflow-step model — what one MANDATORY WORKFLOW step looks like.

Mirrors v1's WorkflowStepDefinition shape so a port of v1's prompt
generator can read this without translation: id, name, instructions,
optional gate, optional evaluation criteria, tool/subagent references,
todo marks, and downstream routes.

Kept separate from `SkillDefinition.workflow_steps` because the two are
different concerns — agent-level MANDATORY workflow vs per-skill
recommended workflow. A given agent can have both: skill workflows are
context the model reads, the agent workflow is the procedure it must
execute on every message.

The model layer is intentionally storage-only. Rendering lives in
open_agent_compiler/compiler/dialects/opencode/workflow_prompt/.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GateLogic = Literal["all", "any"]


class GateCheck(BaseModel):
    """One variable=value check in a gate."""

    model_config = ConfigDict(frozen=True)

    variable: str
    value: str


class Gate(BaseModel):
    """Conditional execution — step runs only if checks pass under logic."""

    model_config = ConfigDict(frozen=True)

    logic: GateLogic = "all"
    checks: tuple[GateCheck, ...] = ()

    @model_validator(mode="after")
    def _checks_non_empty(self) -> "Gate":
        if not self.checks:
            raise ValueError("Gate.checks must contain at least one GateCheck")
        return self


class Criterion(BaseModel):
    """One evaluation question the agent must answer at this step."""

    model_config = ConfigDict(frozen=True)

    name: str
    question: str
    possible_values: tuple[str, ...] = ()


class Route(BaseModel):
    """If `criteria_name` evaluates to `value`, jump to `goto_step`."""

    model_config = ConfigDict(frozen=True)

    criteria_name: str
    value: str
    goto_step: int


class ToolUse(BaseModel):
    """A reference to a tool used in this step, plus an optional usage note.

    Tools themselves are defined on the agent (skills + extra_tools) — this
    is just the lookup key the renderer uses to pull docs in.
    """

    model_config = ConfigDict(frozen=True)

    tool_name: str
    note: str | None = None


class WorkflowStepDefinition(BaseModel):
    """One step in an agent's MANDATORY WORKFLOW.

    Most fields are optional; only `id` and `name` are required so an
    agent author can stub steps before filling in the detail.
    """

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    instructions: str = ""
    todo_name: str | None = Field(
        default=None,
        description=(
            "Identifier for this step in the todo list. Defaults to `name`."
            " Steps that share a todo_name share one todo item."
        ),
    )
    todo_description: str = ""
    gate: Gate | None = None
    evaluates: tuple[Criterion, ...] = ()
    tool_uses: tuple[ToolUse, ...] = ()
    subagents: tuple[str, ...] = Field(
        default=(),
        description="Subagent names to invoke at this step (mode picked from agent.subagents).",
    )
    marks_done: tuple[str, ...] = Field(
        default=(),
        description="Todo item names this step marks completed.",
    )
    routes: tuple[Route, ...] = ()

    def effective_todo_name(self) -> str:
        return self.todo_name or self.name
