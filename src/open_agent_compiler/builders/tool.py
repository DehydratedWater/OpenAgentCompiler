"""Fluent builder for ToolDefinition."""

from __future__ import annotations

from open_agent_compiler._types import ToolDefinition
from open_agent_compiler.builders._base import Builder


class ToolBuilder(Builder[ToolDefinition]):
    """Build a ToolDefinition with a fluent API."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> ToolBuilder:
        self._name: str | None = None
        self._description: str | None = None
        self._parameters: dict[str, object] = {}
        return self

    def name(self, name: str) -> ToolBuilder:
        self._name = name
        return self

    def description(self, description: str) -> ToolBuilder:
        self._description = description
        return self

    def parameter(self, key: str, schema: object) -> ToolBuilder:
        self._parameters[key] = schema
        return self

    def build(self) -> ToolDefinition:
        if not self._name:
            raise ValueError("ToolDefinition requires a name")
        if not self._description:
            raise ValueError("ToolDefinition requires a description")
        return ToolDefinition(
            name=self._name,
            description=self._description,
            parameters=dict(self._parameters),
        )
