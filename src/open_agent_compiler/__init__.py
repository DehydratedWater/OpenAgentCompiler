"""OpenAgentCompiler — Python-first agent framework compiling to OpenCode agents."""

__version__ = "0.1.0"

from open_agent_compiler._types import (
    ActionDefinition,
    AgentPermissions,
    StreamFormat,
    ToolPermissions,
)
from open_agent_compiler.compiler import compile_agent
from open_agent_compiler.runtime import ScriptTool
from open_agent_compiler.writers import OpenCodeWriter

__all__ = [
    "ActionDefinition",
    "AgentPermissions",
    "OpenCodeWriter",
    "ScriptTool",
    "StreamFormat",
    "ToolPermissions",
    "__version__",
    "compile_agent",
]
