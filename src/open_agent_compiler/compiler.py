"""Compiler: AgentDefinition -> backend-specific dict."""

from __future__ import annotations

from typing import Any

from open_agent_compiler._types import AgentDefinition, ToolDefinition


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


def _build_bash_permissions(tools: list[ToolDefinition]) -> dict[str, str]:
    """Build bash permission dict: deny all, then allow each tool script."""
    perms: dict[str, str] = {"*": "deny"}
    for t in tools:
        perms[f"uv run scripts/{t.file_path} *"] = "allow"
    return perms


def _generate_tool_docs(tool: ToolDefinition) -> str:
    """Generate CLI usage documentation for a single tool."""
    lines: list[str] = []
    lines.append(f"### {tool.name}")
    lines.append(f"{tool.description}")
    lines.append("")

    # CLI usage
    args_parts: list[str] = []
    for p in tool.parameters:
        if p.required:
            args_parts.append(f"--{p.name} <{p.param_type}>")
        else:
            default_str = f" (default: {p.default})" if p.default else ""
            args_parts.append(f"[--{p.name} <{p.param_type}>{default_str}]")
    args_str = " ".join(args_parts)
    lines.append("```bash")
    lines.append(f"uv run scripts/{tool.file_path} {args_str}")
    lines.append("```")

    # Stdin streaming example
    if tool.stream_format and tool.stream_field:
        lines.append("")
        fmt_val = tool.stream_format.value
        lines.append(f"Stdin streaming (`{tool.stream_field}` via stdin as {fmt_val}):")
        other_args = " ".join(
            f"--{p.name} <{p.param_type}>"
            for p in tool.parameters
            if p.name != tool.stream_field and p.required
        )
        other_str = f" {other_args}" if other_args else ""
        lines.append("```bash")
        lines.append(f'echo "data" | uv run scripts/{tool.file_path}{other_str}')
        lines.append("```")

    # JSON mode
    lines.append("")
    lines.append("JSON stdin mode:")
    lines.append("```bash")
    lines.append(f"echo '{{...}}' | uv run scripts/{tool.file_path} --json")
    lines.append("```")

    # Parameters table
    if tool.parameters:
        lines.append("")
        lines.append("Parameters:")
        for p in tool.parameters:
            req = "required" if p.required else "optional"
            default_str = f", default: {p.default}" if p.default else ""
            lines.append(
                f"- `{p.name}` ({p.param_type}, {req}{default_str}): {p.description}"
            )

    return "\n".join(lines)


def _compile_opencode(defn: AgentDefinition) -> dict[str, Any]:
    all_tools = _collect_all_tools(defn)
    bash_perms = _build_bash_permissions(all_tools)
    scripts = [t.file_path for t in all_tools]

    # Build tool docs lookup
    tool_docs: dict[str, str] = {}
    for t in all_tools:
        tool_docs[t.name] = _generate_tool_docs(t)

    # Build skills with auto-appended tool usage docs
    compiled_skills: list[dict[str, Any]] = []
    for s in defn.skills:
        skill_tool_names = [t.name for t in s.tools]
        # Auto-append tool usage docs
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
        "tools": {
            "bash": bash_perms,
        },
        "scripts": scripts,
        "skills": compiled_skills,
    }
