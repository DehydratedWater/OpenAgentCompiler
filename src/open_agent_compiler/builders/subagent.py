"""Fluent builder for SubagentDefinition."""

from __future__ import annotations

from open_agent_compiler._types import SubagentDefinition
from open_agent_compiler.builders._base import Builder


class SubagentBuilder(Builder[SubagentDefinition]):
    """Build a SubagentDefinition with a fluent API."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> SubagentBuilder:
        self._name: str | None = None
        self._description: str | None = None
        self._notes: str = ""
        self._mode: str = "subagent"
        return self

    def name(self, name: str) -> SubagentBuilder:
        self._name = name
        return self

    def description(self, description: str) -> SubagentBuilder:
        self._description = description
        return self

    def notes(self, notes: str) -> SubagentBuilder:
        self._notes = notes
        return self

    def mode(self, mode: str) -> SubagentBuilder:
        """Set invocation mode: "subagent" (Task tool) or "primary" (bash)."""
        self._mode = mode
        return self

    def build(self) -> SubagentDefinition:
        if not self._name:
            raise ValueError("SubagentDefinition requires a name")
        if not self._description:
            raise ValueError("SubagentDefinition requires a description")
        return SubagentDefinition(
            name=self._name,
            description=self._description,
            notes=self._notes,
            mode=self._mode,
        )
