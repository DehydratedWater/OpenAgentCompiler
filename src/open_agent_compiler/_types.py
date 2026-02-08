"""Core data types — frozen dataclasses and enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ModelProvider(StrEnum):
    """Supported LLM providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    LOCAL = "local"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Immutable description of a tool an agent can invoke."""

    name: str
    description: str
    parameters: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Immutable runtime configuration for an agent."""

    model: str = "claude-sonnet-4-5-20250929"
    provider: ModelProvider = ModelProvider.ANTHROPIC
    temperature: float = 0.0
    max_tokens: int = 4096


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Immutable, fully-specified agent ready for compilation."""

    name: str
    description: str
    config: AgentConfig = field(default_factory=AgentConfig)
    tools: tuple[ToolDefinition, ...] = ()
    system_prompt: str = ""
