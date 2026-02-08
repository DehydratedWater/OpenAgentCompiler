"""Compiler: AgentDefinition -> backend-specific dict."""

from __future__ import annotations

from typing import Any, Literal

from open_agent_compiler._types import AgentDefinition


def compile_agent(
    definition: AgentDefinition,
    target: Literal["claude_code", "opencode"] = "claude_code",
) -> dict[str, Any]:
    """Compile an AgentDefinition into a backend-specific configuration dict."""
    if target == "claude_code":
        return _compile_claude_code(definition)
    if target == "opencode":
        return _compile_opencode(definition)
    raise ValueError(f"Unknown target: {target!r}")


def _compile_claude_code(defn: AgentDefinition) -> dict[str, Any]:
    return {
        "backend": "claude_code",
        "name": defn.name,
        "description": defn.description,
        "model": defn.config.model,
        "provider": str(defn.config.provider),
        "temperature": defn.config.temperature,
        "max_tokens": defn.config.max_tokens,
        "system_prompt": defn.system_prompt,
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in defn.tools
        ],
    }


def _compile_opencode(defn: AgentDefinition) -> dict[str, Any]:
    return {
        "backend": "opencode",
        "agent": {
            "name": defn.name,
            "description": defn.description,
            "system_prompt": defn.system_prompt,
        },
        "model": {
            "id": defn.config.model,
            "provider": str(defn.config.provider),
            "temperature": defn.config.temperature,
            "max_tokens": defn.config.max_tokens,
        },
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in defn.tools
        ],
    }
