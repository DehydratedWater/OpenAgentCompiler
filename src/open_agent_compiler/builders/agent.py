"""Fluent builder for AgentDefinition."""

from __future__ import annotations

from open_agent_compiler._types import AgentConfig, AgentDefinition, ToolDefinition
from open_agent_compiler.builders._base import Builder


class AgentBuilder(Builder[AgentDefinition]):
    """Build an AgentDefinition with a fluent API."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> AgentBuilder:
        self._name: str | None = None
        self._description: str | None = None
        self._config: AgentConfig = AgentConfig()
        self._tools: list[ToolDefinition] = []
        self._system_prompt: str = ""
        return self

    def name(self, name: str) -> AgentBuilder:
        self._name = name
        return self

    def description(self, description: str) -> AgentBuilder:
        self._description = description
        return self

    def config(self, config: AgentConfig) -> AgentBuilder:
        self._config = config
        return self

    def tool(self, tool: ToolDefinition) -> AgentBuilder:
        self._tools.append(tool)
        return self

    def system_prompt(self, prompt: str) -> AgentBuilder:
        self._system_prompt = prompt
        return self

    def build(self) -> AgentDefinition:
        if not self._name:
            raise ValueError("AgentDefinition requires a name")
        if not self._description:
            raise ValueError("AgentDefinition requires a description")
        return AgentDefinition(
            name=self._name,
            description=self._description,
            config=self._config,
            tools=tuple(self._tools),
            system_prompt=self._system_prompt,
        )
