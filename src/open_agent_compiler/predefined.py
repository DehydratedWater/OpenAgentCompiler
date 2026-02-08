"""Predefined tools and skills for common infrastructure patterns."""

from __future__ import annotations

from open_agent_compiler._types import (
    ActionDefinition,
    SkillDefinition,
    ToolDefinition,
    UsageExample,
)


def subagent_todo_tool() -> ToolDefinition:
    """Predefined tool for subagent progress tracking via file-based todo system."""
    return ToolDefinition(
        name="subagent-todo",
        description="File-based todo list for subagent progress tracking",
        actions=(
            ActionDefinition(
                command_pattern="uv run scripts/subagent_todo.py *",
                description="Manage subagent todo list (init, add, update, list, get, delete, clear, cleanup)",  # noqa: E501
                usage_example='uv run scripts/subagent_todo.py init "agent_name"',
            ),
        ),
        script_files=("subagent_todo.py",),
        examples=(
            UsageExample(
                name="init",
                description="Initialize a new todo list for this agent",
                command='uv run scripts/subagent_todo.py init "{agent_name}"',
            ),
            UsageExample(
                name="add",
                description="Add a task to the todo list",
                command='uv run scripts/subagent_todo.py add "{agent_name}" --run-id "{run_id}" --subject "Task name" --description "What to do" --active-form "Doing task..."',  # noqa: E501
            ),
            UsageExample(
                name="update",
                description="Update a task status",
                command='uv run scripts/subagent_todo.py update "{agent_name}" "{task_id}" --run-id "{run_id}" --status "completed"',  # noqa: E501
            ),
            UsageExample(
                name="list",
                description="List all tasks and their statuses",
                command='uv run scripts/subagent_todo.py list "{agent_name}" --run-id "{run_id}"',  # noqa: E501
            ),
        ),
    )


def subagent_todo_skill() -> SkillDefinition:
    """Skill teaching agents how to use subagent_todo for progress tracking."""
    return SkillDefinition(
        name="progress-tracking",
        description="Track workflow progress using file-based todo system",
        instructions=(
            "## Progress Tracking (MANDATORY)\n"
            "\n"
            "You MUST track your progress using `subagent_todo.py`.\n"
            "This is a file-based todo system since subagents cannot use "
            "the built-in todoread/todowrite tools.\n"
            "\n"
            "### Workflow\n"
            "\n"
            "1. **Initialize** your todo list at the start of every run\n"
            "2. **Add** one task per workflow step\n"
            "3. **Update** each task to `completed` as you finish it\n"
            "4. **List** all tasks at the end to verify completion\n"
            "\n"
            "The `init` command returns a `run_id` — use it for all subsequent calls.\n"
            "The `add` command returns a `task.id` — save it for updating status later."
        ),
        tools=(subagent_todo_tool(),),
    )


def opencode_manager_tool() -> ToolDefinition:
    """Predefined tool for managing OpenCode server and running agents."""
    return ToolDefinition(
        name="opencode-manager",
        description="Manage OpenCode web server and run agents programmatically",
        actions=(
            ActionDefinition(
                command_pattern="uv run scripts/opencode_manager.py *",
                description="Manage OpenCode server and execute agents",
                usage_example="uv run scripts/opencode_manager.py server status",
            ),
        ),
        script_files=("opencode_manager.py",),
        examples=(
            UsageExample(
                name="server-start",
                description="Start the OpenCode web server",
                command="uv run scripts/opencode_manager.py server start",
            ),
            UsageExample(
                name="server-status",
                description="Check if the OpenCode server is running",
                command="uv run scripts/opencode_manager.py server status",
            ),
            UsageExample(
                name="run-agent",
                description="Run an agent with a prompt",
                command='uv run scripts/opencode_manager.py run --agent "workflows/handler-glm-45-air" "Process this request"',  # noqa: E501
            ),
        ),
    )


def agent_orchestration_skill() -> SkillDefinition:
    """Skill teaching agents how to orchestrate other primary agents."""
    return SkillDefinition(
        name="agent-orchestration",
        description="Run and manage other primary agents via OpenCode server",
        instructions=(
            "## Agent Orchestration\n"
            "\n"
            "Use `opencode_manager.py` to run other primary agents programmatically.\n"
            "\n"
            "### Server Management\n"
            "\n"
            "The web server provides a monitoring UI and must be running before "
            "executing agents:\n"
            "\n"
            "1. Check status: `uv run scripts/opencode_manager.py server status`\n"
            "2. Start if needed: `uv run scripts/opencode_manager.py server start`\n"
            "\n"
            "### Running Agents\n"
            "\n"
            "Execute an agent with:\n"
            "```bash\n"
            'uv run scripts/opencode_manager.py run --agent "agent/path" "prompt"\n'
            "```\n"
            "\n"
            "The agent runs as a subprocess. Output and logs are captured automatically.\n"  # noqa: E501
            "Check recent logs with: `uv run scripts/opencode_manager.py logs`"
        ),
        tools=(opencode_manager_tool(),),
    )
