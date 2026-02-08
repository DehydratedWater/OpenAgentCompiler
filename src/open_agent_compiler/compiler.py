"""Compiler: AgentDefinition -> backend-specific dict."""

from __future__ import annotations

from typing import Any

from open_agent_compiler._types import (
    AgentDefinition,
    AgentPermissions,
    SubagentDefinition,
    ToolDefinition,
    ToolPermissions,
    WorkflowStepDefinition,
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
    """Convert a ToolPermissions frozen dataclass to a dict.

    Boolean ``False`` for bash/skill/mcp emits ``key: false`` (disable entirely).
    MCP tuple patterns become top-level entries (e.g. ``"zai-mcp-*": false``).
    """
    result: dict[str, Any] = {}
    # MCP top-level pattern entries first (sequential evaluation)
    if not isinstance(perms.mcp, bool) and perms.mcp:
        for mcp_pattern, allowed in perms.mcp:
            result[mcp_pattern] = allowed
    # bash: False → disabled, tuple → pattern dict
    if isinstance(perms.bash, bool):
        result["bash"] = perms.bash
    elif perms.bash:
        result["bash"] = {pattern: rule for pattern, rule in perms.bash}
    result["read"] = perms.read
    result["write"] = perms.write
    result["edit"] = perms.edit
    result["task"] = perms.task
    result["todoread"] = perms.todoread
    result["todowrite"] = perms.todowrite
    # skill: False → disabled, tuple → pattern dict
    if isinstance(perms.skill, bool):
        result["skill"] = perms.skill
    elif perms.skill:
        result["skill"] = {name: rule for name, rule in perms.skill}
    # mcp: False → disabled entirely
    if isinstance(perms.mcp, bool):
        result["mcp"] = perms.mcp
    return result


def _agent_permissions_to_dict(perms: AgentPermissions) -> dict[str, Any]:
    """Convert an AgentPermissions frozen dataclass to a dict.

    Fields are emitted in order: extra (top-level patterns) → tool → mcp →
    bash → task → doom_loop, matching v2 convention.
    """
    result: dict[str, Any] = {}
    # Top-level extras first (e.g. "zai-mcp-*": "deny")
    for pattern, rule in perms.extra:
        result[pattern] = rule
    # Nested subsections
    if perms.tool:
        result["tool"] = {p: r for p, r in perms.tool}
    if perms.mcp:
        result["mcp"] = {p: r for p, r in perms.mcp}
    if perms.bash:
        result["bash"] = {p: r for p, r in perms.bash}
    if perms.task:
        result["task"] = {p: r for p, r in perms.task}
    result["doom_loop"] = perms.doom_loop
    return result


def _auto_tool_permissions(
    all_tools: list[ToolDefinition],
    defn: AgentDefinition,
) -> dict[str, Any]:
    """Auto-generate tool permission dict from tools and skills.

    When ``defn.auto_mcp_deny`` is True (default), ``"zai-mcp-*": false``
    is emitted first for sequential evaluation.
    """
    # Bash permissions from tool actions — deny first
    bash_perms: dict[str, str] = {"*": "deny"}
    for t in all_tools:
        for action in t.actions:
            bash_perms[action.command_pattern] = "allow"

    result: dict[str, Any] = {}

    # MCP deny first (sequentially evaluated, must precede other entries)
    if defn.auto_mcp_deny:
        result["zai-mcp-*"] = False

    result["bash"] = bash_perms
    result["read"] = False
    result["write"] = False
    result["edit"] = False
    result["task"] = False
    result["todoread"] = False
    result["todowrite"] = False

    # Workflow needs progress tracking
    if defn.workflow:
        if defn.mode == "subagent":
            # Subagents use subagent_todo.py instead of todoread/todowrite
            result["todoread"] = False
            result["todowrite"] = False
            bash_perms["uv run scripts/subagent_todo.py *"] = "allow"
        else:
            result["todoread"] = True
            result["todowrite"] = True

    # Subagents need task
    if defn.subagents:
        result["task"] = True

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


def _build_tool_lookup(defn: AgentDefinition) -> dict[str, ToolDefinition]:
    """Build name -> ToolDefinition lookup from agent tools + skill tools."""
    lookup: dict[str, ToolDefinition] = {}
    for t in defn.tools:
        lookup[t.name] = t
    for skill in defn.skills:
        for t in skill.tools:
            if t.name not in lookup:
                lookup[t.name] = t
    return lookup


def _build_tool_skill_lookup(
    defn: AgentDefinition,
) -> dict[str, str]:
    """Build tool_name -> skill_name mapping for skill-owned tools."""
    lookup: dict[str, str] = {}
    for skill in defn.skills:
        for t in skill.tools:
            if t.name not in lookup:
                lookup[t.name] = skill.name
    return lookup


def _render_tool_use_docs(
    step: WorkflowStepDefinition,
    tool_lookup: dict[str, ToolDefinition],
    tool_skill_lookup: dict[str, str],
) -> str:
    """Render tool documentation for a step's tool_uses."""
    if not step.tool_uses:
        return ""

    lines: list[str] = ["**Tools for this step:**", ""]
    for tu in step.tool_uses:
        tool = tool_lookup.get(tu.tool_name)
        if tool is None:
            continue

        skill_name = tool_skill_lookup.get(tool.name)
        if skill_name:
            lines.append(
                f"**{tool.name}** (skill: `{skill_name}`) — {tool.description}"
            )
        else:
            lines.append(f"**{tool.name}** — {tool.description}")
        lines.append("")

        # Filter examples
        examples = tool.examples
        if tu.example_names:
            examples = tuple(e for e in examples if e.name in tu.example_names)

        for ex in examples:
            lines.append(f"{ex.description}:")
            lines.append("```bash")
            lines.append(ex.command)
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def _compile_workflow_prompt(defn: AgentDefinition) -> str:
    """Generate the full system prompt for a workflow agent."""
    tool_lookup = _build_tool_lookup(defn)
    tool_skill_lookup = _build_tool_skill_lookup(defn)
    is_subagent = defn.mode == "subagent"
    agent_name = defn.name
    parts: list[str] = []

    # Preamble
    if defn.preamble:
        parts.append(defn.preamble)
        parts.append("")

    # Subagents section
    if defn.subagents:
        parts.append("## Your Subagents")
        parts.append("")
        for i, sa in enumerate(defn.subagents):
            parts.append(f"### {i}. `{sa.name}` ({sa.description})")
            if sa.notes:
                parts.append(sa.notes)
            parts.append("")

    # Skills section
    if defn.skills:
        parts.append("## Your Skills")
        parts.append("")
        for skill in defn.skills:
            parts.append(f"### `{skill.name}` — {skill.description}")
            if skill.instructions:
                parts.append(skill.instructions)
            if skill.tools:
                tool_names = ", ".join(f"`{t.name}`" for t in skill.tools)
                parts.append(f"Tools: {tool_names}")
            parts.append("")

    # Mandatory Workflow header
    parts.append("## MANDATORY WORKFLOW")
    parts.append("")
    parts.append("Follow these steps for EVERY incoming message.")
    if is_subagent:
        parts.append("**Use `subagent_todo.py` to track your progress!**")
    else:
        parts.append("**Use todowrite and todoread tools to track your progress!**")
    parts.append("")

    # Collect unique todo items (preserving first-seen order)
    todo_items: list[tuple[str, str]] = []
    seen_todos: set[str] = set()
    for step in defn.workflow:
        resolved_name = step.todo_name or step.name
        if resolved_name not in seen_todos:
            seen_todos.add(resolved_name)
            todo_items.append((resolved_name, step.todo_description))

    # STEP 0: Create Task List / Initialize Progress Tracking
    if is_subagent:
        parts.append("### STEP 0: Initialize Progress Tracking (FIRST!)")
        parts.append("")
        parts.append("**Before doing anything else, initialize your todo list:**")
        parts.append("")
        parts.append("```bash")
        parts.append(f'uv run scripts/subagent_todo.py init "{agent_name}"')
        parts.append("```")
        parts.append("")
        parts.append(
            "Save the `run_id` from the response — you need it for all subsequent calls."  # noqa: E501
        )
        parts.append("")
        parts.append("Then create your tasks:")
        for i, (name, desc) in enumerate(todo_items, 1):
            if desc:
                parts.append(f"{i}. `{name}` — {desc}")
            else:
                parts.append(f"{i}. `{name}`")
            parts.append("```bash")
            parts.append(
                f'uv run scripts/subagent_todo.py add "{agent_name}" '
                f'--run-id "{{run_id}}" '
                f'--subject "{name}"'
                + (f' --description "{desc}"' if desc else "")
                + f' --active-form "Working on: {name}"'
            )
            parts.append("```")
        parts.append("")
        parts.append(
            "Save each task's `id` from the response for updating status later."
        )
    else:
        parts.append("### STEP 0: Create Task List (FIRST!)")
        parts.append("")
        parts.append("**Before doing anything else, create tasks using todowrite:**")
        parts.append("")
        parts.append("Use todowrite to create these tasks:")
        for i, (name, desc) in enumerate(todo_items, 1):
            if desc:
                parts.append(f'{i}. "{name}" - {desc}')
            else:
                parts.append(f'{i}. "{name}"')
    parts.append("")
    parts.append("CRITICAL: YOU MUST EXECUTE ALL POINTS WITHOUT ANY USER INPUT,")
    parts.append("DO NOT STOP UNTIL YOU FINISHED ALL POINTS FROM YOUR TODO LIST")
    parts.append("")
    parts.append("---")
    parts.append("")

    # Each workflow step
    for step in defn.workflow:
        parts.append(f"### STEP {step.id}: {step.name}")
        parts.append("")

        # Gate block
        if step.gate:
            checks = step.gate.checks
            if len(checks) == 1:
                var, val = checks[0]
                parts.append(f"**Condition:** Only execute if `{var}` = `{val}`")
            elif step.gate.logic == "all":
                parts.append("**Condition (ALL must be true):**")
                for var, val in checks:
                    parts.append(f"- `{var}` = `{val}`")
            else:  # any
                parts.append("**Condition (ANY must be true):**")
                for var, val in checks:
                    parts.append(f"- `{var}` = `{val}`")
            parts.append("If condition is not met, skip this step.")
            parts.append("")

        # Tool use docs
        tool_docs = _render_tool_use_docs(step, tool_lookup, tool_skill_lookup)
        if tool_docs:
            parts.append(tool_docs)

        # Evaluation criteria
        if step.evaluates:
            parts.append("**Evaluate the following criteria:**")
            for crit in step.evaluates:
                if crit.possible_values:
                    vals = " | ".join(f"`{v}`" for v in crit.possible_values)
                    parts.append(f"- **{crit.name}**: {crit.question}")
                    parts.append(f"  Possible values: {vals}")
                else:
                    parts.append(f"- **{crit.name}**: {crit.question}")
            parts.append("")

        # Instructions
        if step.instructions:
            parts.append(step.instructions)
            parts.append("")

        # Marks done
        if is_subagent:
            for name in step.marks_done:
                parts.append("**Mark task as completed:**")
                parts.append("```bash")
                parts.append(
                    f'uv run scripts/subagent_todo.py update "{agent_name}" '
                    f'"{{task_id}}" --run-id "{{run_id}}" --status "completed"'
                )
                parts.append("```")
                parts.append(f'(where `{{task_id}}` is the id for "{name}")')
        else:
            for name in step.marks_done:
                parts.append(f'**todowrite: Mark "{name}" as done**')
        if step.marks_done:
            parts.append("")

        # Routes
        if step.routes:
            parts.append("**Based on evaluation, route to:**")
            for route in step.routes:
                parts.append(
                    f"- If `{route.criteria_name}` = `{route.value}` "
                    f"\u2192 Go to **STEP {route.goto_step}**"
                )
            parts.append("")

        parts.append("---")
        parts.append("")

    # Final checklist
    parts.append("## FINAL CHECKLIST - Before You Finish")
    parts.append("")
    if is_subagent:
        parts.append("**Verify all tasks completed:**")
        parts.append("")
        parts.append("```bash")
        parts.append(
            f'uv run scripts/subagent_todo.py list "{agent_name}" --run-id "{{run_id}}"'
        )
        parts.append("```")
        parts.append("")
        parts.append('All tasks must show status "completed" before finishing!')
    else:
        parts.append("**Use todoread to verify all tasks are completed!**")
    parts.append("")
    parts.append("**ASK YOURSELF:**")
    for name, _desc in todo_items:
        parts.append(f'- \u2705 Did I complete "{name}"?')
    parts.append("")

    # Postamble
    if defn.postamble:
        parts.append(defn.postamble)
        parts.append("")

    return "\n".join(parts)


def _compile_subagent_md(sa: SubagentDefinition) -> dict[str, Any]:
    """Compile a SubagentDefinition into a standalone agent dict for writing."""
    # Extract directory and filename from name like "persona/twily_quick_ack-glm-45-air"
    if "/" in sa.name:
        parts = sa.name.rsplit("/", 1)
        agent_dir = parts[0]
        filename = parts[1]
    else:
        agent_dir = ""
        filename = sa.name

    return {
        "name": filename,
        "agent_dir": agent_dir,
        "description": sa.description,
        "mode": "subagent",
        "notes": sa.notes,
    }


def _merge_tool_permissions(
    auto: dict[str, Any],
    explicit: ToolPermissions,
) -> dict[str, Any]:
    """Merge explicit tool permission overrides into auto-generated permissions.

    Only fields that differ from ``ToolPermissions()`` defaults are applied,
    so ``ToolPermissions(read=True)`` overlays *only* ``read`` without
    clobbering auto-generated bash/skill/task rules.
    """
    defaults = ToolPermissions()
    result = dict(auto)

    # Simple boolean fields
    for field in ("read", "write", "edit", "task", "todoread", "todowrite"):
        val = getattr(explicit, field)
        if val != getattr(defaults, field):
            result[field] = val

    # bash: bool disables entirely, tuple adds patterns
    if explicit.bash != defaults.bash:
        if isinstance(explicit.bash, bool):
            result["bash"] = explicit.bash
        elif explicit.bash and isinstance(result.get("bash"), dict):
            for pattern, rule in explicit.bash:
                result["bash"][pattern] = rule

    # skill: bool disables entirely, tuple adds patterns
    if explicit.skill != defaults.skill:
        if isinstance(explicit.skill, bool):
            result["skill"] = explicit.skill
        elif explicit.skill:
            existing = result.get("skill")
            if isinstance(existing, dict):
                for name, rule in explicit.skill:
                    existing[name] = rule
            else:
                result["skill"] = {n: r for n, r in explicit.skill}

    # mcp: bool disables entirely, tuple adds top-level patterns
    if explicit.mcp != defaults.mcp:
        if isinstance(explicit.mcp, bool):
            result["mcp"] = explicit.mcp
        elif explicit.mcp:
            for pattern, allowed in explicit.mcp:
                result[pattern] = allowed

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

    # Build tool permissions — always auto-generate, merge explicit overrides
    tool_perms = _auto_tool_permissions(all_tools, defn)
    if defn.tool_permissions is not None:
        tool_perms = _merge_tool_permissions(tool_perms, defn.tool_permissions)

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

    # System prompt: use workflow prompt if workflow is defined
    system_prompt = defn.system_prompt
    if defn.workflow:
        system_prompt = _compile_workflow_prompt(defn)

    # Build agent section (drives .md frontmatter)
    agent_section: dict[str, Any] = {
        "name": defn.name,
        "description": defn.description,
        "system_prompt": system_prompt,
    }
    if defn.mode:
        agent_section["mode"] = defn.mode
    if defn.variant:
        agent_section["variant"] = defn.variant
    if defn.temperature is not None:
        agent_section["temperature"] = defn.temperature
    if defn.top_p is not None:
        agent_section["top_p"] = defn.top_p
    if defn.min_p is not None:
        agent_section["min_p"] = defn.min_p
    if defn.top_k is not None:
        agent_section["top_k"] = defn.top_k
    if defn.presence_penalty is not None:
        agent_section["presence_penalty"] = defn.presence_penalty
    if defn.hidden:
        agent_section["hidden"] = defn.hidden
    if defn.color:
        agent_section["color"] = defn.color
    if defn.steps > 0:
        agent_section["steps"] = defn.steps
    if defn.options:
        agent_section["options"] = {k: v for k, v in defn.options}
    if defn.agent_dir:
        agent_section["agent_dir"] = defn.agent_dir
    if defn.trigger_command:
        agent_section["trigger_command"] = defn.trigger_command
    if defn.input_placeholder:
        agent_section["input_placeholder"] = defn.input_placeholder

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

    # Compiled subagent dicts for standalone .md files
    if defn.subagents:
        result["subagents_compiled"] = [
            _compile_subagent_md(sa) for sa in defn.subagents
        ]

    # Agent permissions — always generate doom_loop baseline
    if defn.permissions is not None:
        result["permission"] = _agent_permissions_to_dict(defn.permissions)
    elif defn.subagents:
        # Auto-generate subagent permissions
        task_perms = (
            ("*", "deny"),
            *((sa.name, "allow") for sa in defn.subagents),
        )
        auto_perms = AgentPermissions(doom_loop="deny", task=task_perms)
        result["permission"] = _agent_permissions_to_dict(auto_perms)
    else:
        result["permission"] = _agent_permissions_to_dict(AgentPermissions())

    return result
