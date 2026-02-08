"""OpenAgentCompiler — Python-first agent framework compiling to OpenCode agents."""

__version__ = "0.1.0"

from open_agent_compiler._types import (
    ActionDefinition,
    AgentPermissions,
    CompactionConfig,
    ConditionGate,
    ConditionRoute,
    Criterion,
    ModelConfig,
    ModelLimits,
    ModelOptions,
    ProviderConfig,
    ProviderOptions,
    StreamFormat,
    SubagentDefinition,
    ToolPermissions,
    ToolUse,
    UsageExample,
    WorkflowStepDefinition,
)
from open_agent_compiler.compiler import compile_agent
from open_agent_compiler.predefined import (
    agent_orchestration_skill,
    opencode_manager_tool,
    subagent_todo_skill,
    subagent_todo_tool,
)
from open_agent_compiler.runtime import ScriptTool
from open_agent_compiler.writers import OpenCodeWriter

__all__ = [
    "ActionDefinition",
    "AgentPermissions",
    "CompactionConfig",
    "ConditionGate",
    "ConditionRoute",
    "Criterion",
    "ModelConfig",
    "ModelLimits",
    "ModelOptions",
    "OpenCodeWriter",
    "ProviderConfig",
    "ProviderOptions",
    "ScriptTool",
    "StreamFormat",
    "SubagentDefinition",
    "ToolPermissions",
    "ToolUse",
    "UsageExample",
    "WorkflowStepDefinition",
    "__version__",
    "agent_orchestration_skill",
    "compile_agent",
    "opencode_manager_tool",
    "subagent_todo_skill",
    "subagent_todo_tool",
]
