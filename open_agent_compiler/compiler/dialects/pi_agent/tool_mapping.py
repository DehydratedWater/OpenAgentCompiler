"""Map open-agent-compiler tool definitions to pi agent tool names.

Pi agents declare allowed tools in frontmatter as a comma-separated list.
Built-in pi tool names are:
- `read`: Read files
- `bash`: Execute bash commands
- `grep`: Search files with grep
- `find`: Find files
- `ls`: List directory contents
- `write`: Write files
- `edit`: Edit files (exact-line replacement)
- `task`: Spawn subagents (provided by pi-subagents extension)

Extension tools use the `ext:<extension>/<tool>` syntax.

This module maps from OAC's tool model (ToolDefinition with bash_tool
and json_tool) to pi's tool name list.
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentVariant


# OAC tool names → pi tool names
# When an OAC tool has a bash_tool, it maps to pi's `bash` tool
# When an OAC tool has a json_tool, it may map to a custom tool or `bash`
_OAC_TOOL_TO_PI_TOOL: dict[str, str] = {
    "read": "read",
    "write": "write",
    "edit": "edit",
    "bash": "bash",
    "grep": "grep",
    "find": "find",
    "ls": "ls",
    "task": "task",
    "todoread": "read",  # pi doesn't have todoread, use read
    "todowrite": "write",  # pi doesn't have todowrite, use write
}


def map_tools_for_pi(agent: AgentVariant) -> tuple[list[str], list[str]]:
    """Return (allowed_tools, disallowed_tools) for this agent.

    Derives from:
    - agent_definition.extra_tools (explicit tool declarations)
    - agent_definition.skills (tools referenced in workflow_steps)
    - agent_definition.tool_permissions (boolean toggles for read/write/edit/mcp)
    - agent_definition.subagents (if any, add "task" tool)
    - agent_definition.workflow + todo_mode (if todo_mode != "none", add todoread/todowrite equivalents)

    When tool_permissions is None (unset), all tools are allowed by default
    (backward-compat). When set, only tools with True toggles are allowed;
    explicitly denied tools appear in disallowed_tools.

    Returns a tuple of (sorted allowed list, sorted disallowed list).
    """
    defn = agent.agent_definition
    tools_set: set[str] = set()
    disallowed: set[str] = set()

    perm_toggles = defn.tool_permissions
    permissions_explicit = perm_toggles is not None

    if not permissions_explicit:
        # No explicit permissions — default to allowing basic tools
        tools_set.add("read")
        tools_set.add("bash")
    else:
        # Explicit permissions: only add tools that are allowed
        # bash is always allowed (no bash toggle in ToolPermissions) — it's
        # the fundamental execution tool and pi agents need it to run scripts.
        tools_set.add("bash")
        if perm_toggles.read:
            tools_set.add("read")
        else:
            disallowed.add("read")
        if perm_toggles.write:
            tools_set.add("write")
        else:
            disallowed.add("write")
        if perm_toggles.edit:
            tools_set.add("edit")
        else:
            disallowed.add("edit")
        if perm_toggles.mcp:
            # MCP tools are extensions in pi — we don't add them here
            # Users configure MCP servers in pi settings
            pass

    # Map extra_tools
    for tool in defn.extra_tools:
        pi_tool = _OAC_TOOL_TO_PI_TOOL.get(tool.header.name)
        if pi_tool:
            tools_set.add(pi_tool)
        else:
            # Unknown tool — skip or log warning
            pass

    # Map skills workflow_steps tools
    for skill in defn.skills:
        for wf_step in skill.workflow_steps:
            for tool in wf_step.tools_used:
                pi_tool = _OAC_TOOL_TO_PI_TOOL.get(tool.header.name)
                if pi_tool:
                    tools_set.add(pi_tool)

    # Subagents: if the agent has subagents, it needs the `task` tool
    # (pi-subagents provides this via the Agent() tool)
    if defn.subagents:
        tools_set.add("task")

    # Todo mode: if the agent uses todos, it needs read/write for todo tracking
    # Pi doesn't have dedicated todo tools, but agents can use read/write
    # to manage todo files or use the task tool for subagent-based tracking
    # We don't add special todo tools for pi

    # A tool added via extra_tools/skills can re-add a denied built-in
    # (e.g. a skill's workflow_steps includes a tool named 'write' that maps
    # to pi's 'write'). Ensure disallowed tools don't appear in the allowed
    # set — that would produce contradictory frontmatter.
    tools_set -= disallowed

    # Convert to sorted lists for deterministic output
    return sorted(tools_set), sorted(disallowed)
