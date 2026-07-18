"""Permission compilation for one AgentVariant.

The OpenCode runtime enforces a default-deny stance plus an allowlist of
specific bash command patterns or named custom tools. We honor the
agent's `chosen_format(tool)` so a tool offering both bash + JSON only
emits the contract(s) the agent has actually opted into.
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentVariant
from open_agent_compiler.model.core.tools_model import ToolDefinition


def _gather_tools(variant: AgentVariant) -> list[ToolDefinition]:
    seen: dict[str, ToolDefinition] = {}
    for tool in variant.agent_definition.extra_tools:
        seen.setdefault(tool.header.name, tool)
    for skill in variant.agent_definition.skills:
        for wf in skill.workflow_steps:
            for tool in wf.tools_used:
                seen.setdefault(tool.header.name, tool)
    return list(seen.values())


def _bash_allow_patterns(tool: ToolDefinition) -> list[str]:
    allowed = list(getattr(tool.bash_tool.permission_bash, "allowed_commands", []))
    if allowed:
        return allowed
    # Fall back to positive examples — the first token of each example is
    # treated as the command pattern to permit. We keep the entire example
    # so OpenCode's exact-prefix matching works.
    return list(tool.bash_tool.positive_examples)


def generate_permissions(agent: AgentVariant) -> dict:
    permissions: dict = {
        "*": "deny",
        "bash": {"*": "deny"},
        "skill": {"*": "deny"},
    }
    tools_dict: dict = {
        "read": False,
        "write": False,
        "edit": False,
        "task": False,
        "todoread": False,
        "todowrite": False,
        "mcp": False,
        "bash": {"*": "deny"},
        "skill": {"*": "deny"},
    }

    for skill in agent.agent_definition.skills:
        permissions["skill"][skill.name] = "allow"
        tools_dict["skill"][skill.name] = "allow"

    # Enable the Task tool when the agent has subagent-mode children.
    # Without this, the SECURITY POLICY block says "you may invoke
    # <subagent>" but the runtime denies the Task call. Subagents in
    # primary mode use opencode_manager.py via bash instead — they
    # don't need permission.task.
    task_targets = [
        sa for sa in agent.agent_definition.subagents
        if (sa.mode or "subagent") == "subagent"
    ]
    if task_targets:
        permissions["task"] = "allow"
        tools_dict["task"] = True

    # Primary-mode subagents are invoked via the bundled opencode_manager.py
    # dispatcher. The parent needs the bash allowlist entry to actually
    # spawn them — the SECURITY POLICY ALLOWED block lists each by name
    # but without this permission entry the runtime denies the call.
    primary_subagents = [
        sa for sa in agent.agent_definition.subagents
        if (sa.mode or "subagent") == "primary"
    ]
    if primary_subagents:
        pattern = "uv run scripts/opencode_manager.py run --agent *"
        permissions["bash"][pattern] = "allow"
        tools_dict["bash"][pattern] = "allow"

    # Primary agents with a workflow + non-none todo_mode invoke
    # todoread/todowrite to track progress. Subagent-mode agents use
    # the bundled subagent_todo.py via bash (auto-allowlisted by the
    # compile_scripts auto-include path) so they don't need these.
    has_workflow = bool(agent.agent_definition.workflow)
    todo_mode = agent.agent_definition.todo_mode
    if (
        agent.agent_mode == "primary"
        and has_workflow
        and todo_mode != "none"
    ):
        permissions["todoread"] = "allow"
        permissions["todowrite"] = "allow"
        tools_dict["todoread"] = True
        tools_dict["todowrite"] = True

    # Honour per-agent boolean toggles (read/write/edit/mcp) from
    # AgentDefinition.tool_permissions. These map straight onto the
    # permission block — the model needs both the permission entry AND
    # the tool: block entry, so set both.
    perm_toggles = agent.agent_definition.tool_permissions
    if perm_toggles is not None:
        if perm_toggles.read:
            permissions["read"] = "allow"
            tools_dict["read"] = True
        if perm_toggles.write:
            permissions["write"] = "allow"
            tools_dict["write"] = True
        if perm_toggles.edit:
            permissions["edit"] = "allow"
            tools_dict["edit"] = True
        if perm_toggles.mcp:
            permissions["mcp"] = "allow"
            tools_dict["mcp"] = True

    # MCP per-server allowlists. Each declared server gets its own
    # permission.mcp.<name> entry; when allowed_tools is non-empty,
    # only those specific tools are allowed and everything else
    # exposed by the server is denied via a nested `*: deny` default.
    # Two agents in the same compile can safely declare different
    # server subsets — the per-agent emission keeps them isolated.
    mcp_servers = agent.agent_definition.mcp_servers
    if mcp_servers:
        permissions.setdefault("mcp", {})
        # If a boolean mcp toggle was set above, it produced
        # permissions["mcp"] = "allow" (a string). Replace with a
        # dict so per-server entries can coexist.
        if not isinstance(permissions["mcp"], dict):
            permissions["mcp"] = {}
        tools_dict.setdefault("mcp", {})
        if not isinstance(tools_dict["mcp"], dict):
            tools_dict["mcp"] = {}
        for server in mcp_servers:
            if server.allowed_tools:
                # Restricted: only the named tools allowed; default deny.
                server_block: dict = {"*": "deny"}
                for tool_name in server.allowed_tools:
                    server_block[tool_name] = "allow"
                permissions["mcp"][server.name] = server_block
                tools_dict["mcp"][server.name] = server_block
            else:
                permissions["mcp"][server.name] = "allow"
                tools_dict["mcp"][server.name] = "allow"

    tools = _gather_tools(agent)
    for tool in tools:
        fmt = agent.agent_definition.chosen_format(tool)
        emit_bash = fmt in ("bash", "both") and tool.bash_tool is not None
        emit_json = fmt in ("json", "both") and tool.json_tool is not None

        if emit_bash:
            value = tool.bash_tool.permission_bash.value
            for cmd in _bash_allow_patterns(tool):
                permissions["bash"][cmd] = value
                tools_dict["bash"][cmd] = value

        if emit_json:
            value = tool.json_tool.permission_json.value
            permissions[tool.header.name] = value
            tools_dict[tool.header.name] = value

    if len(permissions["bash"]) == 1:
        del permissions["bash"]
    if len(tools_dict["bash"]) == 1:
        del tools_dict["bash"]
    if len(permissions["skill"]) == 1:
        del permissions["skill"]
    if len(tools_dict["skill"]) == 1:
        del tools_dict["skill"]

    # opencode's `tool:` block is an enable/disable SWITCH (booleans), NOT a
    # permission map — granular command/skill/server allowlists live ONLY in
    # the `permission:` block. opencode >=1.17 treats a dict value here as
    # "disabled" and silently strips the tool, so an agent compiled with
    # `tool.bash: {<allowlist>}` ends up with NO bash tool at all and can only
    # narrate. Collapse any remaining nested allowlist (bash/skill/mcp) to
    # `True`: its presence means "this tool has allowed entries" -> enable it;
    # the deny-by-default + specific allows are still enforced via `permission`.
    for key, val in list(tools_dict.items()):
        if isinstance(val, dict):
            tools_dict[key] = True

    return {"permission": permissions, "tool": tools_dict}
