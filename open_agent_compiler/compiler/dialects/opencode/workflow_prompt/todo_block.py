"""STEP 0 task-list initialization + workspace-init STEP 0a.

Two top-of-workflow blocks driven by AgentDefinition.todo_mode and
AgentDefinition.workspace. Both reference bundled infrastructure
scripts that Phase 4 wires into the compiled tree — until then the
emitted bash commands assume `subagent_todo.py` and `workspace_io.py`
live at `scripts/` under the project root.
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentVariant


def _agent_name(agent: AgentVariant) -> str:
    """Postfixed agent name used in subagent_todo + workspace_io calls."""
    return agent.agent_definition.header.name + agent.postfix


def render_workspace_init(agent: AgentVariant) -> str:
    defn = agent.agent_definition
    if not defn.workspace:
        return ""
    resolved_ws = defn.workspace.replace("{name}", _agent_name(agent))
    return (
        "### STEP 0a: Initialize Workspace Session (FIRST!)\n"
        "\n"
        "**Create an isolated session directory for this run:**\n"
        "\n"
        "```bash\n"
        f"uv run scripts/workspace_io.py --command init --workspace {resolved_ws}\n"
        "```\n"
        "\n"
        "Save the `run_id` from the response —"
        " pass it as `--run-id` to all subsequent workspace_io.py calls.\n"
        "\n"
        "---\n"
    )


def _todo_items(agent: AgentVariant) -> list[tuple[str, str]]:
    """Stable de-dup by effective_todo_name, first occurrence wins."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for step in agent.agent_definition.workflow:
        name = step.effective_todo_name()
        if name not in seen:
            seen.add(name)
            out.append((name, step.todo_description))
    return out


def _subagent_init_block(agent_name: str) -> list[str]:
    return [
        "**Before doing anything else, initialize your todo list:**",
        "",
        "```bash",
        f'uv run scripts/subagent_todo.py init "{agent_name}"',
        "```",
        "",
        (
            "Save the `run_id` from the response — "
            "you need it for all subsequent calls."
        ),
        "",
        "Then create your tasks:",
    ]


def _subagent_add_block(agent_name: str, name: str, desc: str) -> list[str]:
    cmd = (
        f'uv run scripts/subagent_todo.py add "{agent_name}" '
        f'--run-id "{{run_id}}" '
        f'--subject "{name}"'
    )
    if desc:
        cmd += f' --description "{desc}"'
    cmd += f' --active-form "Working on: {name}"'
    return ["```bash", cmd, "```"]


def render_todo_step_0(agent: AgentVariant) -> str:
    """Render STEP 0 (task list) per the agent's todo_mode."""
    defn = agent.agent_definition
    if defn.todo_mode == "none":
        return ""
    is_subagent = agent.agent_mode == "subagent"
    agent_name = _agent_name(agent)
    items = _todo_items(agent)
    parts: list[str] = []

    if defn.todo_mode == "strict" and is_subagent:
        parts.append("### STEP 0: Initialize Progress Tracking (FIRST!)")
        parts.append("")
        parts.extend(_subagent_init_block(agent_name))
        for i, (name, desc) in enumerate(items, 1):
            parts.append(
                f"{i}. `{name}`" + (f" — {desc}" if desc else "")
            )
            parts.extend(_subagent_add_block(agent_name, name, desc))
        parts.append("")
        parts.append("Save each task's `id` from the response for updating status later.")
    elif defn.todo_mode == "strict":
        parts.append("### STEP 0: Create Task List (FIRST!)")
        parts.append("")
        parts.append("**Before doing anything else, create tasks using todowrite:**")
        parts.append("")
        parts.append("Use todowrite to create these tasks:")
        for i, (name, desc) in enumerate(items, 1):
            parts.append(
                f'{i}. "{name}"' + (f" - {desc}" if desc else "")
            )
    elif defn.todo_mode == "lazy" and is_subagent:
        parts.append("### STEP 0: Create Task List (FIRST!)")
        parts.append("")
        parts.extend(_subagent_init_block(agent_name))
        for i, (name, desc) in enumerate(items, 1):
            parts.append(
                f"{i}. `{name}`" + (f" — {desc}" if desc else "")
            )
            parts.extend(_subagent_add_block(agent_name, name, desc))
        parts.append("")
        parts.append("Save each task's `id` from the response for updating status later.")
        parts.append("")
        parts.append(
            "You do NOT need to update task status after each step."
            " Focus on completing the work."
        )
    elif defn.todo_mode == "lazy":
        parts.append("### STEP 0: Create Task List (FIRST!)")
        parts.append("")
        parts.append("**Before doing anything else, create tasks using todowrite:**")
        parts.append("")
        parts.append("Use todowrite to create these tasks:")
        for i, (name, desc) in enumerate(items, 1):
            parts.append(
                f'{i}. "{name}"' + (f" - {desc}" if desc else "")
            )
        parts.append("")
        parts.append(
            "You do NOT need to update task status after each step."
            " Focus on completing the work."
        )

    parts.append("")
    parts.append("---")
    parts.append("")
    return "\n".join(parts)


def render_mark_done(agent: AgentVariant, names: tuple[str, ...]) -> str:
    """Render mark-done bash/todowrite lines for a step.

    Only emits content under strict mode; lazy and none return "".
    """
    defn = agent.agent_definition
    if defn.todo_mode != "strict" or not names:
        return ""
    agent_name = _agent_name(agent)
    parts: list[str] = []
    if agent.agent_mode == "subagent":
        for name in names:
            parts.append("**Mark task as completed:**")
            parts.append("```bash")
            parts.append(
                f'uv run scripts/subagent_todo.py update "{agent_name}" '
                f'"{{task_id}}" --run-id "{{run_id}}" --status "completed"'
            )
            parts.append("```")
            parts.append(f'(where `{{task_id}}` is the id for "{name}")')
    else:
        for name in names:
            parts.append(f'**todowrite: Mark "{name}" as done**')
    parts.append("")
    return "\n".join(parts)


def render_strict_verification(agent: AgentVariant) -> str:
    """Final-checklist verification block — only for strict mode."""
    defn = agent.agent_definition
    if defn.todo_mode != "strict":
        return ""
    agent_name = _agent_name(agent)
    if agent.agent_mode == "subagent":
        return (
            "**Verify all tasks completed:**\n"
            "\n"
            "```bash\n"
            f'uv run scripts/subagent_todo.py list "{agent_name}"'
            f' --run-id "{{run_id}}"\n'
            "```\n"
            "\n"
            'All tasks must show status "completed" before finishing!\n'
        )
    return "**Use todoread to verify all tasks are completed!**\n"
