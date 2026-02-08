"""OpenAgentCompiler — Python-first agent framework compiling to OpenCode agents."""

__version__ = "0.1.0"

from open_agent_compiler._types import StreamFormat
from open_agent_compiler.compiler import compile_agent
from open_agent_compiler.runtime import ScriptTool

__all__ = ["ScriptTool", "StreamFormat", "__version__", "compile_agent"]
