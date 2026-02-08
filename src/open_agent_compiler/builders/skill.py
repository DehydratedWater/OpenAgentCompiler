"""Fluent builder for SkillDefinition."""

from __future__ import annotations

from open_agent_compiler._types import SkillDefinition, ToolDefinition
from open_agent_compiler.builders._base import Builder


class SkillBuilder(Builder[SkillDefinition]):
    """Build a SkillDefinition with a fluent API."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> SkillBuilder:
        self._name: str | None = None
        self._description: str | None = None
        self._instructions: str = ""
        self._tools: list[ToolDefinition] = []
        return self

    def name(self, name: str) -> SkillBuilder:
        self._name = name
        return self

    def description(self, description: str) -> SkillBuilder:
        self._description = description
        return self

    def instructions(self, instructions: str) -> SkillBuilder:
        self._instructions = instructions
        return self

    def tool(self, tool: ToolDefinition) -> SkillBuilder:
        self._tools.append(tool)
        return self

    def build(self) -> SkillDefinition:
        if not self._name:
            raise ValueError("SkillDefinition requires a name")
        if not self._description:
            raise ValueError("SkillDefinition requires a description")
        return SkillDefinition(
            name=self._name,
            description=self._description,
            instructions=self._instructions,
            tools=tuple(self._tools),
        )
