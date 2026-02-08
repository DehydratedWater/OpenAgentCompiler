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
class ActionDefinition:
    """A single invocable bash command action within a tool."""

    command_pattern: str  # "uv run scripts/send_message.py *"
    description: str  # "Send a text message to Telegram"
    usage_example: str  # 'uv run scripts/send_message.py "Hello!"'


@dataclass(frozen=True, slots=True)
class ToolPermissions:
    """Full tool: permission block for an agent."""

    bash: tuple[tuple[str, str], ...] = ()  # (pattern, "allow"|"deny"|"ask")
    read: bool = False
    write: bool = False
    edit: bool = False
    task: bool = False
    todoread: bool = False
    todowrite: bool = False
    skill: tuple[tuple[str, str], ...] = ()  # (name, "allow"|"deny")
    mcp: tuple[tuple[str, bool], ...] = ()  # ("zai-mcp-*", False)


@dataclass(frozen=True, slots=True)
class AgentPermissions:
    """The permission: section in agent frontmatter."""

    doom_loop: str = "deny"  # "allow" | "deny"
    task: tuple[tuple[str, str], ...] = ()  # agent path patterns


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Immutable description of a tool an agent can invoke."""

    name: str
    description: str
    actions: tuple[ActionDefinition, ...] = ()
    script_files: tuple[str, ...] = ()


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
    skill_instructions: tuple[tuple[str, str], ...] = ()  # (name, when)
    system_prompt: str = ""
    tool_permissions: ToolPermissions | None = None
    permissions: AgentPermissions | None = None
    mode: str = ""
