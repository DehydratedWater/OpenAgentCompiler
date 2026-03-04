"""Compiler: AgentDefinition -> backend-specific dict."""

from __future__ import annotations

import re
import warnings
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
    *,
    postfix: str = "",
    inline_skills: bool = False,
    todo_mode: str = "strict",
) -> dict[str, Any]:
    """Compile an AgentDefinition into a backend-specific configuration dict.

    Parameters
    ----------
    postfix:
        Appended to agent name and subagent references (e.g. ``"-test-glm45air"``).
        Skill names are **not** postfixed.
    inline_skills:
        When ``True``, skill instructions and tool docs are inlined into the
        system prompt and no standalone SKILL.md files are emitted.
    todo_mode:
        Controls todo/progress tracking in compiled agents:
        - ``"strict"`` (default): Full todo enforcement — init list, mark done
          after every step, verify all completed at end.
        - ``"lazy"``: Steps listed but no per-step "mark done" instructions,
          no final verification. Todo tools still available.
        - ``"none"``: No todo tools at all — no todoread/todowrite permissions,
          no subagent_todo.py. Workflow steps still listed as numbered steps.
    """
    if todo_mode not in ("strict", "lazy", "none"):
        raise ValueError(
            f"todo_mode must be 'strict', 'lazy', or 'none', got {todo_mode!r}"
        )
    if target == "opencode":
        return _compile_opencode(
            definition,
            postfix=postfix,
            inline_skills=inline_skills,
            todo_mode=todo_mode,
        )
    raise ValueError(f"Unknown target: {target!r}")


def _postfix_sa_name(sa_name: str, postfix: str) -> str:
    """Apply *postfix* to a subagent name, preserving directory prefix."""
    if not postfix:
        return sa_name
    if "/" in sa_name:
        d, base = sa_name.rsplit("/", 1)
        return f"{d}/{base}{postfix}"
    return sa_name + postfix


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
    lines: list[str] = [f"#### Script: {tool.name}", tool.description, ""]
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
    # Only emit doom_loop when "allow" — "deny" is covered by "*": "deny"
    if perms.doom_loop == "allow":
        result["doom_loop"] = perms.doom_loop
    return result


# Default MCP tool glob patterns — covers all known global MCP servers.
# With ``"*": "deny"`` in the permission section, these are only needed as
# selective *allow* entries when an agent opts out of MCP deny.
_DEFAULT_MCP_PATTERNS: tuple[str, ...] = (
    "zai-mcp-*",
    "web-search-prime*",
    "web-reader*",
    "zread*",
)


def _auto_tool_permissions(
    all_tools: list[ToolDefinition],
    defn: AgentDefinition,
    agent_name: str = "",
    inline_skills: bool = False,
    postfix: str = "",
    todo_mode: str = "strict",
) -> dict[str, Any]:
    """Auto-generate tool permission dict from tools and skills.

    When ``defn.auto_mcp_deny`` is truthy, MCP deny patterns are emitted
    in the ``tool:`` section to hide MCP tools from the model.

    *agent_name* is the (possibly postfixed) agent name, used for workspace
    path resolution.  Falls back to ``defn.name`` when empty.
    """

    agent_name = agent_name or defn.name

    # Bash permissions from tool actions — deny first
    bash_perms: dict[str, str] = {"*": "deny"}
    for t in all_tools:
        for action in t.actions:
            bash_perms[action.command_pattern] = "allow"

    result: dict[str, Any] = {}

    # MCP deny first (sequentially evaluated, must precede other entries)
    if defn.auto_mcp_deny:
        patterns: tuple[str, ...] = (
            _DEFAULT_MCP_PATTERNS if defn.auto_mcp_deny is True else defn.auto_mcp_deny  # type: ignore[assignment]
        )
        for pattern in patterns:
            result[pattern] = False

    result["bash"] = bash_perms
    result["read"] = False
    result["write"] = False
    result["edit"] = False
    result["task"] = False
    result["todoread"] = False
    result["todowrite"] = False

    # Workspace — add workspace_io.py bash pattern, keep write/edit false
    if defn.workspace:
        bash_perms["uv run scripts/workspace_io.py *"] = "allow"

    # Workflow needs progress tracking (unless todo_mode="none")
    if defn.workflow and todo_mode != "none":
        if defn.mode == "subagent":
            # Subagents use subagent_todo.py instead of todoread/todowrite
            result["todoread"] = False
            result["todowrite"] = False
            bash_perms["uv run scripts/subagent_todo.py *"] = "allow"
        else:
            result["todoread"] = True
            result["todowrite"] = True

    # Subagent invocation:
    # - mode="subagent" → Task tool with subagent_type parameter
    # - mode="primary" → opencode_manager.py via bash
    if defn.subagents:
        has_task_subs = any(sa.mode == "subagent" for sa in defn.subagents)
        has_bash_subs = any(sa.mode == "primary" for sa in defn.subagents)
        if has_bash_subs:
            for sa in defn.subagents:
                if sa.mode == "primary":
                    sa_name = _postfix_sa_name(sa.name, postfix)
                    bash_perms[
                        f"uv run scripts/opencode_manager.py run*--agent*{sa_name}*"
                    ] = "allow"
        if has_task_subs:
            result["task"] = True

    # Skill permissions — disable when inlined, else deny-all unless specific
    if inline_skills:
        result["skill"] = False
    elif defn.skills:
        skill_perms: dict[str, str] = {"*": "deny"}
        for s in defn.skills:
            skill_perms[s.name] = "allow"
        result["skill"] = skill_perms
    else:
        result["skill"] = False

    # MCP — always deny-all by default
    result["mcp"] = False

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

                if (
                    model.input_modalities is not None
                    or model.output_modalities is not None
                ):
                    modalities: dict[str, list[str]] = {}
                    if model.input_modalities is not None:
                        modalities["input"] = list(model.input_modalities)
                    modalities["output"] = (
                        list(model.output_modalities)
                        if model.output_modalities is not None
                        else ["text"]
                    )
                    m["modalities"] = modalities

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


def _compile_workflow_prompt(
    defn: AgentDefinition,
    agent_name: str = "",
    postfix: str = "",
    inline_skills: bool = False,
    todo_mode: str = "strict",
) -> str:
    """Generate the full system prompt for a workflow agent.

    *agent_name* is the (possibly postfixed) agent name used in
    subagent_todo.py calls and workspace resolution.

    *todo_mode* controls progress tracking:
    ``"strict"`` = full todo enforcement, ``"lazy"`` = steps listed but no
    per-step marks, ``"none"`` = no todo tools at all.
    """
    agent_name = agent_name or defn.name
    tool_lookup = _build_tool_lookup(defn)
    tool_skill_lookup = _build_tool_skill_lookup(defn)
    is_subagent = defn.mode == "subagent"

    # Build subagent name → mode lookup for step invocation injection
    sa_mode_lookup: dict[str, str] = {sa.name: sa.mode for sa in defn.subagents}
    parts: list[str] = []

    # Preamble
    if defn.preamble:
        parts.append(defn.preamble)
        parts.append("")

    # Skills section — inline or reference
    if defn.skills and inline_skills:
        parts.append("## Available Bash Scripts")
        parts.append("")
        parts.append(
            "**IMPORTANT:** These are NOT callable tools. To use them, run the bash "
            "commands shown below using the `bash` tool."
        )
        parts.append("")
        for skill in defn.skills:
            parts.append(f"### {skill.description}")
            if skill.instructions:
                parts.append(skill.instructions)
            parts.append("")
            # Inline full tool action docs for each skill tool
            for t in skill.tools:
                parts.append(_generate_action_docs(t))
                parts.append("")
    elif defn.skills:
        parts.append("## Your Skills (use via bash)")
        parts.append("")
        for skill in defn.skills:
            parts.append(f"### {skill.description}")
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
    if todo_mode != "none":
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

    # Workspace init (before STEP 0 task list)
    if defn.workspace:
        resolved_ws = defn.workspace.replace("{name}", agent_name)
        parts.append("### STEP 0a: Initialize Workspace Session (FIRST!)")
        parts.append("")
        parts.append("**Create an isolated session directory for this run:**")
        parts.append("")
        parts.append("```bash")
        parts.append(
            f"uv run scripts/workspace_io.py --command init --workspace {resolved_ws}"
        )
        parts.append("```")
        parts.append("")
        parts.append(
            "Save the `run_id` from the response —"
            " pass it as `--run-id` to all subsequent workspace_io.py calls."
        )
        parts.append("")
        parts.append("---")
        parts.append("")

    # STEP 0: Create Task List / Initialize Progress Tracking
    if todo_mode == "strict":
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
            parts.append(
                "**Before doing anything else, create tasks using todowrite:**"
            )
            parts.append("")
            parts.append("Use todowrite to create these tasks:")
            for i, (name, desc) in enumerate(todo_items, 1):
                if desc:
                    parts.append(f'{i}. "{name}" - {desc}')
                else:
                    parts.append(f'{i}. "{name}"')
    elif todo_mode == "lazy":
        parts.append("### STEP 0: Create Task List (FIRST!)")
        parts.append("")
        if is_subagent:
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
            parts.append(
                "**Before doing anything else, create tasks using todowrite:**"
            )
            parts.append("")
            parts.append("Use todowrite to create these tasks:")
            for i, (name, desc) in enumerate(todo_items, 1):
                if desc:
                    parts.append(f'{i}. "{name}" - {desc}')
                else:
                    parts.append(f'{i}. "{name}"')
        parts.append("")
        parts.append(
            "You do NOT need to update task status after each step."
            " Focus on completing the work."
        )
    # todo_mode == "none": no STEP 0 at all

    parts.append("")
    parts.append("CRITICAL: YOU MUST EXECUTE ALL POINTS WITHOUT ANY USER INPUT,")
    parts.append(
        "DO NOT STOP UNTIL YOU FINISHED ALL STEPS"
        + (" FROM YOUR TODO LIST" if todo_mode != "none" else "")
    )
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

        # Auto-inject subagent invocation syntax based on mode.
        # Use un-postfixed names here — the final postfix rewrite
        # at the end of _compile_workflow_prompt handles postfixing.
        for sa_name in step.subagents:
            sa_mode = sa_mode_lookup.get(sa_name, "subagent")
            if sa_mode == "subagent":
                parts.append(f"**Invoke `{sa_name}` via Task tool:**")
                parts.append(
                    f'`subagent_type: "{sa_name}"`, `prompt: "<your instructions>"`'
                )
            else:
                parts.append(f"**Invoke `{sa_name}` via bash:**")
                parts.append("```bash")
                parts.append(
                    "uv run scripts/opencode_manager.py"
                    f' run --agent "{sa_name}"'
                    ' "<your instructions>"'
                )
                parts.append("```")
            parts.append("")

        # Marks done (only in strict mode)
        if todo_mode == "strict":
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
    if todo_mode == "strict":
        if is_subagent:
            parts.append("**Verify all tasks completed:**")
            parts.append("")
            parts.append("```bash")
            parts.append(
                f'uv run scripts/subagent_todo.py list "{agent_name}"'
                f' --run-id "{{run_id}}"'
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

    result_text = "\n".join(parts)

    # Rewrite agent/subagent names in step instructions to include postfix.
    # Collects names from subagent definitions AND task permission entries.
    if postfix:
        names_to_postfix: set[str] = set()
        for sa in defn.subagents:
            names_to_postfix.add(sa.name)
        if defn.permissions and defn.permissions.task:
            for name, _rule in defn.permissions.task:
                if name != "*":
                    names_to_postfix.add(name)
        # Replace longest names first; use regex negative lookahead to
        # prevent partial matches (e.g. "workflows/todo" matching inside
        # "workflows/todo_goals").
        for name in sorted(names_to_postfix, key=len, reverse=True):
            postfixed = _postfix_sa_name(name, postfix)
            if name != postfixed:
                pattern = re.escape(name) + r"(?![\w])"
                result_text = re.sub(pattern, postfixed, result_text)

    return result_text


def _compile_subagent_md(sa: SubagentDefinition, postfix: str = "") -> dict[str, Any]:
    """Compile a SubagentDefinition into a standalone agent dict for writing."""
    postfixed = _postfix_sa_name(sa.name, postfix)
    # Extract directory and filename from name like "persona/twily_quick_ack-test-abc"
    if "/" in postfixed:
        parts = postfixed.rsplit("/", 1)
        agent_dir = parts[0]
        filename = parts[1]
    else:
        agent_dir = ""
        filename = postfixed

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


def _compile_subagent_section(defn: AgentDefinition, postfix: str = "") -> str:
    """Generate a markdown section documenting available subagents."""
    if not defn.subagents:
        return ""

    task_subs = [sa for sa in defn.subagents if sa.mode == "subagent"]
    bash_subs = [sa for sa in defn.subagents if sa.mode == "primary"]

    lines: list[str] = ["## Available Subagents", ""]

    # Task-invocable subagents (mode: subagent)
    if task_subs:
        lines.append(
            "Invoke subagents using the **Task tool** with the `subagent_type`"
            " parameter set to the agent name shown below."
        )
        lines.append("")
        for sa in task_subs:
            sa_name = _postfix_sa_name(sa.name, postfix)
            lines.append(f"### {sa_name} — {sa.description}")
            if sa.notes:
                lines.append(sa.notes)
            lines.append("")
            lines.append(
                f'Task tool call: `subagent_type: "{sa_name}"`, `prompt: "<your instructions>"`'  # noqa: E501
            )
            lines.append("")

    # Bash-invocable agents (mode: primary — workflows, standalone agents)
    if bash_subs:
        lines.append(
            "Invoke the following agents using `opencode_manager.py` via the"
            " **bash** tool. These are standalone primary agents."
        )
        lines.append("")
        for sa in bash_subs:
            sa_name = _postfix_sa_name(sa.name, postfix)
            lines.append(f"### {sa_name} — {sa.description}")
            if sa.notes:
                lines.append(sa.notes)
            lines.append("")
            lines.append("```bash")
            lines.append(
                f"uv run scripts/opencode_manager.py run --agent {sa_name} <your instructions>"  # noqa: E501
            )
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def _compile_security_policy(
    defn: AgentDefinition,
    agent_name: str = "",
    postfix: str = "",
    inline_skills: bool = False,
) -> str:
    """Generate an explicit SECURITY POLICY section for the agent's prompt."""
    agent_name = agent_name or defn.name
    lines: list[str] = ["## SECURITY POLICY", ""]

    # ALLOWED actions
    lines.append("### ALLOWED actions")
    lines.append("- Bash commands listed in your tool documentation above ONLY")
    read_allowed = defn.tool_permissions and defn.tool_permissions.read
    lines.append(f"- Read files: {'yes' if read_allowed else 'no'}")

    if defn.workspace:
        resolved_ws = defn.workspace.replace("{name}", agent_name)
        lines.append(f"- Write files: only via workspace_io.py to `{resolved_ws}/`")
        lines.append(
            "- Session isolation: use `--command init` first, then"
            " pass `--run-id` to all subsequent calls"
        )
    elif defn.tool_permissions and defn.tool_permissions.write:
        lines.append("- Write files: yes (unrestricted)")
    else:
        lines.append("- Write files: no")

    # Subagents
    if defn.subagents:
        task_subs = [sa for sa in defn.subagents if sa.mode == "subagent"]
        bash_subs = [sa for sa in defn.subagents if sa.mode == "primary"]
        if task_subs:
            sa_names = ", ".join(
                f"`{_postfix_sa_name(sa.name, postfix)}`" for sa in task_subs
            )
            lines.append(
                "- Invoke subagents via Task tool"
                f" (`subagent_type` parameter): {sa_names}"
            )
        if bash_subs:
            sa_names = ", ".join(
                f"`{_postfix_sa_name(sa.name, postfix)}`" for sa in bash_subs
            )
            lines.append(
                "- Invoke agents via bash"
                f" (`opencode_manager.py run --agent`): {sa_names}"
            )
    else:
        lines.append("- Invoke subagents: none")

    # Skills
    if inline_skills:
        lines.append("- Use skills: none (bash scripts are documented in prompt)")
    elif defn.skills:
        sk_names = ", ".join(f"`{s.name}`" for s in defn.skills)
        lines.append(f"- Use skills: {sk_names}")
    else:
        lines.append("- Use skills: none")

    lines.append("")

    # FORBIDDEN section
    lines.append("### FORBIDDEN — You MUST NOT:")
    if defn.workspace:
        lines.append(
            "- Write or create files using the write/edit tools (they are disabled)"
        )
        lines.append(
            "- Create files via bash (no `cat >`, `echo >`, `tee`, `>`, `>>`, `touch`,"
            " `mkdir`, `cp`, `mv` or ANY other file-creating command)"
        )
        lines.append(
            "- Store thoughts, notes, analyses, reports, conclusions,"
            " or ANY intermediate output as files — keep everything in memory"
            " or write to your workspace via workspace_io.py ONLY"
        )
    elif not (defn.tool_permissions and defn.tool_permissions.write):
        lines.append(
            "- Write, create, or modify any files (write/edit tools are disabled)"
        )
        lines.append(
            "- Create files via bash (no `cat >`, `echo >`, `tee`, `>`, `>>`, `touch`,"
            " `mkdir`, `cp`, `mv` or ANY other file-creating command)"
        )
    lines.append("- Run bash commands not listed in your tool documentation")
    if inline_skills or not defn.skills:
        lines.append("- Use any skills (all skills are disabled)")
    else:
        lines.append("- Use skills other than the ones listed above")
    if defn.mode == "subagent" and not defn.subagents:
        lines.append(
            "- Invoke other agents via Task tool"
            " (subagents cannot delegate to other subagents)"
        )
    elif defn.mode == "subagent" and defn.subagents:
        # Has primary children only (Task children blocked by validation)
        bash_subs = [sa for sa in defn.subagents if sa.mode == "primary"]
        if bash_subs:
            sa_names = ", ".join(f"`{sa.name}`" for sa in bash_subs)
            lines.append(
                f"- Invoke agents via bash"
                f" (`opencode_manager.py run --agent`): {sa_names}"
            )
        lines.append(
            "- Invoke agents via Task tool"
            " (subagents cannot delegate to other subagents)"
        )
    elif not defn.subagents:
        lines.append("- Invoke subagents (none are configured for this agent)")
    else:
        task_subs = [sa for sa in defn.subagents if sa.mode == "subagent"]
        bash_subs = [sa for sa in defn.subagents if sa.mode == "primary"]
        lines.append("- Invoke subagents other than the ones listed above")
        if task_subs:
            lines.append(
                "- Use opencode_manager.py to invoke subagents"
                " (use Task tool with `subagent_type` instead)"
            )
        if bash_subs:
            lines.append(
                "- Use Task tool for primary/workflow agents"
                " (use opencode_manager.py instead)"
            )
    lines.append("- Use MCP tools (they are disabled)")
    lines.append(
        "- Create files in the project root or any directory outside your workspace"
    )
    lines.append("- Modify system files or configuration")
    lines.append("")

    return "\n".join(lines)


def _compile_opencode(
    defn: AgentDefinition,
    *,
    postfix: str = "",
    inline_skills: bool = False,
    todo_mode: str = "strict",
) -> dict[str, Any]:
    agent_name = defn.name + postfix

    # Validation: workspace and write=True are mutually exclusive
    has_explicit_write = (
        defn.tool_permissions is not None and defn.tool_permissions.write
    )
    if defn.workspace and has_explicit_write:
        raise ValueError(
            "workspace and write=True are mutually exclusive — "
            "workspace provides controlled writes via workspace_io.py"
        )
    if has_explicit_write and not defn.workspace:
        warnings.warn(
            f"Agent {defn.name!r} uses write=True without a workspace — "
            "consider using .workspace() for sandboxed file I/O",
            stacklevel=2,
        )

    # Subagent-mode agents can invoke primary agents (via opencode_manager.py)
    # but cannot spawn Task-tool subagents (mode="subagent")
    if defn.mode == "subagent" and defn.subagents:
        task_children = [sa for sa in defn.subagents if sa.mode == "subagent"]
        if task_children:
            names = ", ".join(sa.name for sa in task_children)
            raise ValueError(
                f"Agent {defn.name!r} has mode='subagent' but defines"
                f" Task-tool subagents: {names} — subagents cannot"
                " spawn other subagents (use mode='primary' instead)"
            )

    all_tools = _collect_all_tools(defn)

    # Collect all script files
    scripts: list[str] = []
    for t in all_tools:
        for sf in t.script_files:
            if sf not in scripts:
                scripts.append(sf)
    # Add workspace_io.py when workspace is configured
    if defn.workspace and "workspace_io.py" not in scripts:
        scripts.append("workspace_io.py")

    # Build tool docs lookup
    tool_docs: dict[str, str] = {}
    for t in all_tools:
        tool_docs[t.name] = _generate_action_docs(t)

    # Build tool permissions — always auto-generate, merge explicit overrides
    tool_perms = _auto_tool_permissions(
        all_tools,
        defn,
        agent_name=agent_name,
        inline_skills=inline_skills,
        postfix=postfix,
        todo_mode=todo_mode,
    )
    if defn.tool_permissions is not None:
        tool_perms = _merge_tool_permissions(tool_perms, defn.tool_permissions)

    # Build skills with auto-appended tool usage docs
    compiled_skills: list[dict[str, Any]] = []
    if not inline_skills:
        for s in defn.skills:
            skill_tool_names = [t.name for t in s.tools]
            instructions = s.instructions
            relevant_docs = [
                tool_docs[name] for name in skill_tool_names if name in tool_docs
            ]
            if relevant_docs:
                instructions += "\n\n## Available Tools\n\n" + "\n\n".join(
                    relevant_docs
                )
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
        workflow_prompt = _compile_workflow_prompt(
            defn,
            agent_name=agent_name,
            postfix=postfix,
            inline_skills=inline_skills,
            todo_mode=todo_mode,
        )
        # Prepend custom system_prompt to workflow prompt if both exist
        if defn.system_prompt:
            system_prompt = defn.system_prompt.rstrip("\n") + "\n\n" + workflow_prompt
        else:
            system_prompt = workflow_prompt
    elif defn.skills and inline_skills:
        # Non-workflow agents: append inlined skill reference to system prompt
        skill_parts: list[str] = [
            "## Available Bash Scripts",
            "",
            "**IMPORTANT:** These are NOT callable tools. To use them, run the bash "
            "commands shown below using the `bash` tool.",
            "",
        ]
        for skill in defn.skills:
            skill_parts.append(f"### {skill.description}")
            if skill.instructions:
                skill_parts.append(skill.instructions)
            skill_parts.append("")
            for t in skill.tools:
                skill_parts.append(_generate_action_docs(t))
                skill_parts.append("")
        system_prompt = system_prompt.rstrip("\n") + "\n\n" + "\n".join(skill_parts)

    # Rewrite agent/subagent names in system prompt text to include postfix.
    # Done BEFORE appending auto-generated sections (which already use
    # postfixed names) to avoid double-postfixing.
    if postfix and not defn.workflow:
        names_to_postfix: set[str] = set()
        for sa in defn.subagents:
            names_to_postfix.add(sa.name)
        if defn.permissions and defn.permissions.task:
            for name, _rule in defn.permissions.task:
                if name != "*":
                    names_to_postfix.add(name)
        for name in sorted(names_to_postfix, key=len, reverse=True):
            postfixed_sa = _postfix_sa_name(name, postfix)
            if name != postfixed_sa:
                pattern = re.escape(name) + r"(?![\w])"
                system_prompt = re.sub(pattern, postfixed_sa, system_prompt)

    # Append auto-generated subagent documentation
    subagent_section = _compile_subagent_section(defn, postfix=postfix)
    if subagent_section:
        system_prompt = system_prompt.rstrip("\n") + "\n\n" + subagent_section

    # Append security policy
    security_policy = _compile_security_policy(
        defn,
        agent_name=agent_name,
        postfix=postfix,
        inline_skills=inline_skills,
    )
    system_prompt = system_prompt.rstrip("\n") + "\n\n" + security_policy

    # Build agent section (drives .md frontmatter)
    agent_section: dict[str, Any] = {
        "name": agent_name,
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
            _compile_subagent_md(sa, postfix=postfix) for sa in defn.subagents
        ]

    # Agent permissions — always generate doom_loop baseline
    if defn.permissions is not None:
        perms = defn.permissions
        # Postfix subagent names in explicit task permissions
        if postfix and perms.task:
            new_task = tuple(
                (_postfix_sa_name(name, postfix), rule) if name != "*" else (name, rule)
                for name, rule in perms.task
            )
            perms = AgentPermissions(
                doom_loop=perms.doom_loop,
                tool=perms.tool,
                mcp=perms.mcp,
                bash=perms.bash,
                task=new_task,
                extra=perms.extra,
            )
        result["permission"] = _agent_permissions_to_dict(perms)
    elif defn.subagents:
        # Subagents are invoked via bash (opencode_manager.py), not the
        # Task tool.  The bash allow pattern is set in _auto_tool_permissions.
        result["permission"] = _agent_permissions_to_dict(AgentPermissions())
    else:
        result["permission"] = _agent_permissions_to_dict(AgentPermissions())

    # Mirror tool restrictions into the permission: section.
    # The permission: section is reliably enforced in non-interactive
    # ``opencode run`` mode (the tool: section may not be — see bug #6396).
    perm_dict = result["permission"]

    # Global deny — blocks all tools by default.  Only explicit "allow"
    # entries below will re-enable specific capabilities.
    perm_dict["*"] = "deny"

    # read — only allow when explicitly enabled
    if tool_perms.get("read", False):
        perm_dict["read"] = "allow"

    # edit — canonical key covering write, edit, patch, multiedit
    write_ok = tool_perms.get("write", False)
    edit_ok = tool_perms.get("edit", False)
    if write_ok or edit_ok:
        perm_dict["edit"] = "allow"

    # bash — merge deny/allow patterns (always has its own "*": "deny")
    bash_tool = tool_perms.get("bash")
    if isinstance(bash_tool, dict):
        existing_bash = perm_dict.get("bash")
        if isinstance(existing_bash, dict):
            merged = dict(bash_tool)
            merged.update(existing_bash)
            perm_dict["bash"] = merged
        else:
            perm_dict["bash"] = dict(bash_tool)
    elif isinstance(bash_tool, bool) and bash_tool and "bash" not in perm_dict:
        perm_dict["bash"] = {"*": "allow"}

    # skill — only allow when explicitly enabled
    skill_tool = tool_perms.get("skill")
    if isinstance(skill_tool, dict):
        existing_skill = perm_dict.get("skill")
        if isinstance(existing_skill, dict):
            merged = dict(skill_tool)
            merged.update(existing_skill)
            perm_dict["skill"] = merged
        else:
            perm_dict["skill"] = dict(skill_tool)
    elif isinstance(skill_tool, bool) and skill_tool and "skill" not in perm_dict:
        perm_dict["skill"] = "allow"

    # MCP — ``"*": "deny"`` blocks all MCP tools by default.
    # When ``auto_mcp_deny`` is False, emit selective allows to let MCP through.
    if not defn.auto_mcp_deny:
        patterns = _DEFAULT_MCP_PATTERNS
        for pattern in patterns:
            if pattern not in perm_dict:
                perm_dict[pattern] = "allow"

    # todoread / todowrite — only allow when explicitly enabled
    if tool_perms.get("todoread", False):
        perm_dict["todoread"] = "allow"
    if tool_perms.get("todowrite", False):
        perm_dict["todowrite"] = "allow"

    # task — only allow if not already configured and tool says allow
    if "task" not in perm_dict and tool_perms.get("task", False):
        perm_dict["task"] = "allow"

    # doom_loop — move to end so it can override the global "*": "deny"
    if "doom_loop" in perm_dict:
        val = perm_dict.pop("doom_loop")
        perm_dict["doom_loop"] = val

    return result
