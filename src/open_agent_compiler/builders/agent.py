"""Fluent builder for AgentDefinition."""

from __future__ import annotations

from open_agent_compiler._types import (
    AgentConfig,
    AgentDefinition,
    AgentPermissions,
    SkillDefinition,
    ToolDefinition,
    ToolPermissions,
)
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
        self._skills: list[SkillDefinition] = []
        self._skill_instructions: list[tuple[str, str]] = []
        self._system_prompt: str = ""
        self._tool_permissions: ToolPermissions | None = None
        self._permissions: AgentPermissions | None = None
        self._mode: str = ""
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

    def skill(
        self,
        skill: SkillDefinition,
        *,
        instruction: str,
    ) -> AgentBuilder:
        self._skills.append(skill)
        self._skill_instructions.append((skill.name, instruction))
        return self

    def system_prompt(self, prompt: str) -> AgentBuilder:
        self._system_prompt = prompt
        return self

    def tool_permissions(self, perms: ToolPermissions) -> AgentBuilder:
        self._tool_permissions = perms
        return self

    def permissions(self, perms: AgentPermissions) -> AgentBuilder:
        self._permissions = perms
        return self

    def mode(self, mode: str) -> AgentBuilder:
        self._mode = mode
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
            skills=tuple(self._skills),
            skill_instructions=tuple(self._skill_instructions),
            system_prompt=self._system_prompt,
            tool_permissions=self._tool_permissions,
            permissions=self._permissions,
            mode=self._mode,
        )
