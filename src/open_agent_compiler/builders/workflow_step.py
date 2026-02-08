"""Fluent builder for WorkflowStepDefinition."""

from __future__ import annotations

from open_agent_compiler._types import (
    ConditionGate,
    ConditionRoute,
    Criterion,
    ToolUse,
    WorkflowStepDefinition,
)
from open_agent_compiler.builders._base import Builder


class WorkflowStepBuilder(Builder[WorkflowStepDefinition]):
    """Build a WorkflowStepDefinition with a fluent API."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> WorkflowStepBuilder:
        self._id: str | None = None
        self._name: str | None = None
        self._instructions: str = ""
        self._todo_name: str = ""
        self._todo_description: str = ""
        self._subagents: list[str] = []
        self._tool_uses: list[ToolUse] = []
        self._marks_done: list[str] = []
        self._marks_done_called: bool = False
        self._evaluates: list[Criterion] = []
        self._gate_checks: list[tuple[str, str]] = []
        self._gate_logic: str | None = None
        self._routes: list[ConditionRoute] = []
        return self

    def id(self, id: str) -> WorkflowStepBuilder:
        self._id = id
        return self

    def name(self, name: str) -> WorkflowStepBuilder:
        self._name = name
        return self

    def instructions(self, instructions: str) -> WorkflowStepBuilder:
        self._instructions = instructions
        return self

    def todo(self, name: str, description: str = "") -> WorkflowStepBuilder:
        self._todo_name = name
        self._todo_description = description
        return self

    def subagent(self, name: str) -> WorkflowStepBuilder:
        self._subagents.append(name)
        return self

    def use_tool(self, tool_name: str, *example_names: str) -> WorkflowStepBuilder:
        self._tool_uses.append(ToolUse(tool_name, tuple(example_names)))
        return self

    def mark_done(self, *names: str) -> WorkflowStepBuilder:
        self._marks_done.extend(names)
        self._marks_done_called = True
        return self

    def evaluate(
        self, name: str, question: str, *possible_values: str
    ) -> WorkflowStepBuilder:
        self._evaluates.append(Criterion(name, question, tuple(possible_values)))
        return self

    def gate(self, variable: str, value: str) -> WorkflowStepBuilder:
        if self._gate_logic == "any":
            raise ValueError("Cannot mix .gate() (AND) with .gate_any() (OR)")
        self._gate_logic = "all"
        self._gate_checks.append((variable, value))
        return self

    def gate_any(self, variable: str, value: str) -> WorkflowStepBuilder:
        if self._gate_logic == "all":
            raise ValueError("Cannot mix .gate_any() (OR) with .gate() (AND)")
        self._gate_logic = "any"
        self._gate_checks.append((variable, value))
        return self

    def route(self, criteria_name: str, value: str, goto: str) -> WorkflowStepBuilder:
        self._routes.append(ConditionRoute(criteria_name, value, goto))
        return self

    def build(self) -> WorkflowStepDefinition:
        if not self._id:
            raise ValueError("WorkflowStepDefinition requires an id")
        if not self._name:
            raise ValueError("WorkflowStepDefinition requires a name")

        # Resolve todo_name default
        todo_name = self._todo_name or self._name

        # Auto-set marks_done if not explicitly called
        marks_done = tuple(self._marks_done)
        if not self._marks_done_called:
            marks_done = (todo_name,)

        # Build gate if checks exist
        gate: ConditionGate | None = None
        if self._gate_checks:
            gate = ConditionGate(
                checks=tuple(self._gate_checks),
                logic=self._gate_logic or "all",
            )

        return WorkflowStepDefinition(
            id=self._id,
            name=self._name,
            instructions=self._instructions,
            todo_name=todo_name,
            todo_description=self._todo_description,
            subagents=tuple(self._subagents),
            tool_uses=tuple(self._tool_uses),
            marks_done=marks_done,
            evaluates=tuple(self._evaluates),
            gate=gate,
            routes=tuple(self._routes),
        )
