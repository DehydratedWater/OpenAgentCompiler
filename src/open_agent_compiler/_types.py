"""Core data types — frozen dataclasses and enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


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


# -- Rich provider/model hierarchy for opencode.json --


@dataclass(frozen=True, slots=True)
class ProviderOptions:
    """Connection options for a provider."""

    api_key: str = ""
    base_url: str = ""
    timeout: int = 600000
    max_retries: int = 2


@dataclass(frozen=True, slots=True)
class ModelLimits:
    """Token limits for a model."""

    context: int = 131072
    output: int = 32768


@dataclass(frozen=True, slots=True)
class ModelOptions:
    """Sampling options for a model."""

    temperature: float = 1.0
    top_p: float = 1.0
    top_k: int = 0
    min_p: float = 0.0
    presence_penalty: float = 0.0
    extra_body: tuple[tuple[str, str | int | float | bool], ...] = ()


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """A single model within a provider."""

    name: str  # local name "gpt-oss-120b"
    id: str  # actual model ID
    limits: ModelLimits = field(default_factory=ModelLimits)
    options: ModelOptions = field(default_factory=ModelOptions)
    input_modalities: tuple[str, ...] | None = None
    output_modalities: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """A provider with its connection options and models."""

    name: str
    options: ProviderOptions = field(default_factory=ProviderOptions)
    models: tuple[ModelConfig, ...] = ()


@dataclass(frozen=True, slots=True)
class CompactionConfig:
    """Compaction settings for opencode."""

    auto: bool = True
    prune: bool = True


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Immutable runtime configuration for an agent."""

    providers: tuple[ProviderConfig, ...] = ()
    default_model: str = ""  # "provider/model"
    compaction: CompactionConfig = field(default_factory=CompactionConfig)


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
    mode: str = ""  # "subagent" | "primary" | "all"
    variant: str = ""
    temperature: float | None = None
    top_p: float | None = None
    hidden: bool = False
    color: str = ""  # hex "#FF5733" or theme "primary"
    steps: int = 0  # 0 = not set
    options: tuple[tuple[str, str | int | float | bool], ...] = ()
