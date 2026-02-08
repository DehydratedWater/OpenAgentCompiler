"""Compiler: AgentDefinition -> backend-specific dict."""

from __future__ import annotations

from typing import Any

from open_agent_compiler._types import (
    AgentDefinition,
    AgentPermissions,
    ToolDefinition,
    ToolPermissions,
)


def compile_agent(
    definition: AgentDefinition,
    target: str = "opencode",
) -> dict[str, Any]:
    """Compile an AgentDefinition into a backend-specific configuration dict."""
    if target == "opencode":
        return _compile_opencode(definition)
    raise ValueError(f"Unknown target: {target!r}")


def _collect_all_tools(defn: AgentDefinition) -> list[ToolDefinition]:
    """Collect all unique tools from agent-level and skill-level (no duplicates)."""
    seen: set[str] = set()
    tools: list[ToolDefinition] = []
    for t in defn.tools:
        if t.name not in seen:
            seen.add(t.name)
            tools.append(t)
    for skill in defn.skills:
        for t in skill.tools:
            if t.name not in seen:
                seen.add(t.name)
                tools.append(t)
    return tools


def _generate_action_docs(tool: ToolDefinition) -> str:
    """Generate markdown documentation from a tool's actions."""
    lines: list[str] = [f"### {tool.name}", tool.description, ""]
    for action in tool.actions:
        lines.append(action.description)
        lines.append("")
        lines.append("```bash")
        lines.append(action.usage_example)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _tool_permissions_to_dict(perms: ToolPermissions) -> dict[str, Any]:
    """Convert a ToolPermissions frozen dataclass to a dict."""
    result: dict[str, Any] = {}
    if perms.bash:
        result["bash"] = {pattern: rule for pattern, rule in perms.bash}
    result["read"] = perms.read
    result["write"] = perms.write
    result["edit"] = perms.edit
    result["task"] = perms.task
    result["todoread"] = perms.todoread
    result["todowrite"] = perms.todowrite
    if perms.skill:
        result["skill"] = {name: rule for name, rule in perms.skill}
    for mcp_pattern, allowed in perms.mcp:
        result[mcp_pattern] = allowed
    return result


def _agent_permissions_to_dict(perms: AgentPermissions) -> dict[str, Any]:
    """Convert an AgentPermissions frozen dataclass to a dict."""
    result: dict[str, Any] = {"doom_loop": perms.doom_loop}
    if perms.task:
        result["task"] = {pattern: rule for pattern, rule in perms.task}
    return result


def _auto_tool_permissions(
    all_tools: list[ToolDefinition],
    defn: AgentDefinition,
) -> dict[str, Any]:
    """Auto-generate tool permission dict from tools and skills."""
    # Bash permissions from tool actions — deny first
    bash_perms: dict[str, str] = {"*": "deny"}
    for t in all_tools:
        for action in t.actions:
            bash_perms[action.command_pattern] = "allow"

    result: dict[str, Any] = {
        "bash": bash_perms,
        "read": False,
        "write": False,
        "edit": False,
        "task": False,
        "todoread": False,
        "todowrite": False,
    }

    # Skill permissions from agent's skills — deny first
    if defn.skills:
        skill_perms: dict[str, str] = {"*": "deny"}
        for s in defn.skills:
            skill_perms[s.name] = "allow"
        result["skill"] = skill_perms

    return result


def _compile_opencode(defn: AgentDefinition) -> dict[str, Any]:
    all_tools = _collect_all_tools(defn)

    # Collect all script files
    scripts: list[str] = []
    for t in all_tools:
        for sf in t.script_files:
            if sf not in scripts:
                scripts.append(sf)

    # Build tool docs lookup
    tool_docs: dict[str, str] = {}
    for t in all_tools:
        tool_docs[t.name] = _generate_action_docs(t)

    # Build tool permissions
    if defn.tool_permissions is not None:
        tool_perms = _tool_permissions_to_dict(defn.tool_permissions)
    else:
        tool_perms = _auto_tool_permissions(all_tools, defn)

    # Build skills with auto-appended tool usage docs
    compiled_skills: list[dict[str, Any]] = []
    for s in defn.skills:
        skill_tool_names = [t.name for t in s.tools]
        instructions = s.instructions
        relevant_docs = [
            tool_docs[name] for name in skill_tool_names if name in tool_docs
        ]
        if relevant_docs:
            instructions += "\n\n## Available Tools\n\n" + "\n\n".join(relevant_docs)
        compiled_skills.append(
            {
                "name": s.name,
                "description": s.description,
                "instructions": instructions,
                "tools": skill_tool_names,
            }
        )

    # Build agent section
    agent_section: dict[str, Any] = {
        "name": defn.name,
        "description": defn.description,
        "system_prompt": defn.system_prompt,
    }
    if defn.mode:
        agent_section["mode"] = defn.mode

    result: dict[str, Any] = {
        "backend": "opencode",
        "agent": agent_section,
        "model": {
            "id": defn.config.model,
            "provider": str(defn.config.provider),
            "temperature": defn.config.temperature,
            "max_tokens": defn.config.max_tokens,
        },
        "tool": tool_perms,
        "scripts": scripts,
        "skills": compiled_skills,
    }

    if defn.permissions is not None:
        result["permission"] = _agent_permissions_to_dict(defn.permissions)

    # Skill instructions for the agent body
    if defn.skill_instructions:
        result["skill_instructions"] = list(defn.skill_instructions)

    return result
