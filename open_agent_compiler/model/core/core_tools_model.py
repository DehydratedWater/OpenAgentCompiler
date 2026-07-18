"""Core tools that can be attached to any agent at any time.

Core tools are cross-cutting capabilities:
  - opencode_manager: universal agent dispatch/spawn tool
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from open_agent_compiler.model.core.permissions_model import BashToolPermission, JsonToolPermission
from open_agent_compiler.model.core.tools_model import (
    ScriptDefinition,
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
    ToolDefinitionLogicJson,
    ToolScriptDefinition,
)


class OpencodeManagerAction(StrEnum):
    """Supported actions for the opencode_manager tool."""

    DISPATCH = "dispatch"
    SPAWN = "spawn"


def create_opencode_manager_tool(project_root: str | None = None) -> ToolDefinition:
    """Create the opencode_manager tool definition.

    This tool enables any agent to:
      - dispatch: delegate a task to a subagent (same tree)
      - spawn:   spin up a new independent primary agent (new tree)

    Args:
        project_root: Optional project root path for script resolution.
                      If None, uses relative path.

    Returns:
        A fully configured ToolDefinition for opencode_manager.
    """

    script_path = "scripts/opencode_manager.py"
    if project_root:
        full_path = f"{project_root}/{script_path}"
    else:
        full_path = script_path

    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="opencode_manager",
            description=(
                "Universal agent dispatch and spawn tool. "
                "Allows any agent to delegate tasks to subagents (dispatch) or "
                "spin up independent primary agents (spawn), enabling infinite-depth routing."
            ),
            usage_explanation_long=(
                "The opencode_manager is a core tool that can be attached to any agent. "
                "It provides two actions:\n"
                "  - dispatch: delegate a task to a registered subagent within the same compilation tree.\n"
                "  - spawn:   spin up a new independent primary agent, starting a new agent tree.\n\n"
                "This enables infinite-depth routing: any agent can dispatch to subagents, "
                "and any agent can spawn new primary agents that themselves have subagents.\n\n"
                "Usage:\n"
                "  uv run scripts/opencode_manager.py --action dispatch --target-agent-id 'joke_agent_*' --prompt 'Tell me a joke'\n"
                "  uv run scripts/opencode_manager.py --action spawn --target-agent-id 'hello_agent_*' --prompt 'Greet the user'\n"
            ),
            usage_explanation_short=(
                "Dispatch tasks to subagents or spawn new primary agents."
            ),
            rules=[
                "Use 'dispatch' to delegate to a subagent within the same tree.",
                "Use 'spawn' to spin up a new independent primary agent.",
                "Always provide a target_agent_id (exact ID or wildcard pattern).",
                "Always provide a prompt describing the task.",
                "Optional: provide context for additional information.",
            ],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(tool_name="bash", value="allow"),
            positive_examples=[
                "uv run scripts/opencode_manager.py --action dispatch --target-agent-id 'joke_agent_glm-5.1_t0.7' --prompt 'Tell me a joke'",
                "uv run scripts/opencode_manager.py --action spawn --target-agent-id 'hello_agent_*' --prompt 'Greet the user'",
                "uv run scripts/opencode_manager.py --action dispatch --target-agent-id 'joke_agent_*' --prompt 'Tell a joke' --context 'User prefers puns'",
            ],
            negative_examples=[
                "Use python3 instead of uv run",
                "Call the tool without --action flag",
                "Omit --target-agent-id",
            ],
            mode_specific_rules=[
                "Always use 'uv run' to execute the script.",
                "Always include --action, --target-agent-id, and --prompt.",
            ],
        ),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(tool_name="custom_tool", value="allow"),
            positive_examples=[
                "opencode_manager(action='dispatch', target_agent_id='joke_agent_*', prompt='Tell a joke')",
                "opencode_manager(action='spawn', target_agent_id='hello_agent_*', prompt='Greet')",
            ],
            negative_examples=[
                "Call without action parameter",
                "Omit target_agent_id",
            ],
            mode_specific_rules=[
                "Use typed tool call with action, target_agent_id, and prompt.",
            ],
            tool_scripts=[
                ToolScriptDefinition(
                    paths=[Path(full_path)],
                    scripts=[
                        ScriptDefinition(
                            target_file_path=Path(script_path),
                            source_file_path=Path(full_path),
                            source_file_type="python",
                            script_contents=None,
                        )
                    ],
                )
            ],
        ),
    )
