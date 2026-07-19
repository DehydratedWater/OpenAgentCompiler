"""Dialect registry — map target string → Dialect class.

A Dialect is responsible for turning the resolved compilation tree
into platform-specific artifacts. OpenCodeDialect writes the
`.opencode/agents/` shape; ClaudeCodeDialect writes the `.claude/`
variant; PiAgentDialect writes `.pi/agents/` markdown; CodexCompiler
writes `.codex/agents/` TOML for the OpenAI Codex CLI.

CompileScript picks one via its `dialect` field (default "opencode").
External packages can register their own dialects via `register()`.
"""

from __future__ import annotations

from typing import Type

from open_agent_compiler.compiler.core.compiler import Compiler


_REGISTRY: dict[str, Type[Compiler]] = {}


def register(name: str, cls: Type[Compiler]) -> None:
    """Register a Dialect under `name`. Overwrites any existing entry."""
    _REGISTRY[name] = cls


def get(name: str) -> Type[Compiler]:
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown dialect {name!r}; registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def list_dialects() -> list[str]:
    return sorted(_REGISTRY)


def _autoregister() -> None:
    """Eagerly register the bundled dialects.

    Imports are lazy to avoid a cycle: dialect modules import from
    open_agent_compiler.compiler.core which can import back into the registry. This
    function is called from open_agent_compiler/compiler/dialects/__init__.py.
    """
    from open_agent_compiler.compiler.dialects.opencode.compiler import OpenCodeCompiler

    register("opencode", OpenCodeCompiler)

    from open_agent_compiler.compiler.dialects.claude_code.compiler import ClaudeCodeCompiler

    register("claude", ClaudeCodeCompiler)

    from open_agent_compiler.compiler.dialects.pi_agent.compiler import PiAgentCompiler

    register("pi", PiAgentCompiler)

    from open_agent_compiler.compiler.dialects.codex.compiler import CodexCompiler

    register("codex", CodexCompiler)
