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


def _build_provider_dict(defn: AgentDefinition) -> dict[str, Any]:
    """Build the rich provider hierarchy for opencode.json."""
    providers: dict[str, Any] = {}
    for prov in defn.config.providers:
        prov_dict: dict[str, Any] = {}

        # Options — only include non-default values
        opts = prov.options
        if opts.api_key:
            prov_dict.setdefault("options", {})["apiKey"] = opts.api_key
        if opts.base_url:
            prov_dict.setdefault("options", {})["baseURL"] = opts.base_url
        if opts.timeout != 600000:
            prov_dict.setdefault("options", {})["timeout"] = opts.timeout
        if opts.max_retries != 2:
            prov_dict.setdefault("options", {})["maxRetries"] = opts.max_retries

        # Models
        if prov.models:
            models_dict: dict[str, Any] = {}
            for model in prov.models:
                m: dict[str, Any] = {"id": model.id}

                # Limits — only if non-default
                if model.limits.context != 131072 or model.limits.output != 32768:
                    m["limits"] = {
                        "context": model.limits.context,
                        "output": model.limits.output,
                    }

                # Options — only if non-default
                mopts = model.options
                mopts_dict: dict[str, Any] = {}
                if mopts.temperature != 1.0:
                    mopts_dict["temperature"] = mopts.temperature
                if mopts.top_p != 1.0:
                    mopts_dict["topP"] = mopts.top_p
                if mopts.top_k != 0:
                    mopts_dict["topK"] = mopts.top_k
                if mopts.min_p != 0.0:
                    mopts_dict["minP"] = mopts.min_p
                if mopts.presence_penalty != 0.0:
                    mopts_dict["presencePenalty"] = mopts.presence_penalty
                if mopts.extra_body:
                    mopts_dict["extraBody"] = {k: v for k, v in mopts.extra_body}
                if mopts_dict:
                    m["options"] = mopts_dict

                if model.input_modalities is not None:
                    m["inputModalities"] = list(model.input_modalities)
                if model.output_modalities is not None:
                    m["outputModalities"] = list(model.output_modalities)

                models_dict[model.name] = m
            prov_dict["models"] = models_dict

        providers[prov.name] = prov_dict

    return providers


def _build_config_dict(defn: AgentDefinition) -> dict[str, Any]:
    """Build the full opencode.json config dict (no per-agent fields)."""
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
    }

    provider_dict = _build_provider_dict(defn)
    if provider_dict:
        config["provider"] = provider_dict

    if defn.config.default_model:
        config["model"] = defn.config.default_model

    # Compaction
    comp = defn.config.compaction
    config["compaction"] = {"auto": comp.auto, "prune": comp.prune}

    return config


def _build_enriched_skill_instructions(
    defn: AgentDefinition,
) -> list[dict[str, Any]]:
    """Build skill_instructions enriched with tool descriptions."""
    # Map skill name -> skill definition for quick lookup
    skill_map = {s.name: s for s in defn.skills}

    result: list[dict[str, Any]] = []
    for skill_name, instruction in defn.skill_instructions:
        entry: dict[str, Any] = {
            "name": skill_name,
            "instruction": instruction,
        }
        skill_def = skill_map.get(skill_name)
        if skill_def and skill_def.tools:
            entry["tools"] = [
                {"name": t.name, "description": t.description} for t in skill_def.tools
            ]
        else:
            entry["tools"] = []
        result.append(entry)
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

    # Build agent section (drives .md frontmatter)
    agent_section: dict[str, Any] = {
        "name": defn.name,
        "description": defn.description,
        "system_prompt": defn.system_prompt,
    }
    if defn.mode:
        agent_section["mode"] = defn.mode
    if defn.variant:
        agent_section["variant"] = defn.variant
    if defn.temperature is not None:
        agent_section["temperature"] = defn.temperature
    if defn.top_p is not None:
        agent_section["top_p"] = defn.top_p
    if defn.hidden:
        agent_section["hidden"] = defn.hidden
    if defn.color:
        agent_section["color"] = defn.color
    if defn.steps > 0:
        agent_section["steps"] = defn.steps
    if defn.options:
        agent_section["options"] = {k: v for k, v in defn.options}

    # Build config dict (full opencode.json content)
    config_dict = _build_config_dict(defn)

    result: dict[str, Any] = {
        "backend": "opencode",
        "agent": agent_section,
        "config": config_dict,
        "tool": tool_perms,
        "scripts": scripts,
        "skills": compiled_skills,
    }

    # Enriched skill instructions
    if defn.skill_instructions:
        result["skill_instructions"] = _build_enriched_skill_instructions(defn)

    if defn.permissions is not None:
        result["permission"] = _agent_permissions_to_dict(defn.permissions)

    return result
