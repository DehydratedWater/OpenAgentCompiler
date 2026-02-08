"""Core data types — frozen dataclasses and enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ModelProvider(StrEnum):
    """Supported LLM providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    LOCAL = "local"


class StreamFormat(StrEnum):
    """Format for stdin streaming."""

    JSON = "json"
    XML = "xml"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    """Immutable description of a single tool parameter."""

    name: str
    description: str
    param_type: str  # "str", "int", "float", "bool"
    required: bool = True
    default: str | None = None


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Immutable description of a script-based tool an agent can invoke."""

    name: str
    description: str
    file_path: str
    parameters: tuple[ParameterDefinition, ...] = ()
    stream_format: StreamFormat | None = None
    stream_field: str | None = None


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Immutable runtime configuration for an agent."""

    model: str = "claude-sonnet-4-5-20250929"
    provider: ModelProvider = ModelProvider.ANTHROPIC
    temperature: float = 0.0
    max_tokens: int = 4096


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    """Immutable description of a skill an agent can invoke."""

    name: str
    description: str
    instructions: str = ""
    tools: tuple[ToolDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Immutable, fully-specified agent ready for compilation."""

    name: str
    description: str
    config: AgentConfig = field(default_factory=AgentConfig)
    tools: tuple[ToolDefinition, ...] = ()
    skills: tuple[SkillDefinition, ...] = ()
    system_prompt: str = ""
