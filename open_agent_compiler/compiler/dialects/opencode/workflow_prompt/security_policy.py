"""'## SECURITY POLICY' block: explicit ALLOWED + FORBIDDEN actions.

Ports v1 _compile_security_policy (compiler.py:940-1078) with the same
contract: the block lists what the model may do, what it may NOT do,
and is fully contextual to mode / workspace / tool_permissions /
subagents / skills.

The block lives at the very end of the system prompt so it acts as the
final word before the model starts working. v1 places it after the
workflow + postamble; v2 follows the same placement.
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentHeader, AgentVariant, ToolPermissions


def _agent_name(agent: AgentVariant) -> str:
    return agent.agent_definition.header.name + agent.postfix


def _effective_permissions(agent: AgentVariant) -> ToolPermissions:
    return agent.agent_definition.tool_permissions or ToolPermissions()


def _split_subagents(agent: AgentVariant) -> tuple[list[AgentHeader], list[AgentHeader]]:
    task_subs: list[AgentHeader] = []
    bash_subs: list[AgentHeader] = []
    for sa in agent.agent_definition.subagents:
        if (sa.mode or "subagent") == "subagent":
            task_subs.append(sa)
        else:
            bash_subs.append(sa)
    return task_subs, bash_subs


def _allowed_section(agent: AgentVariant) -> list[str]:
    defn = agent.agent_definition
    perms = _effective_permissions(agent)
    lines = ["### ALLOWED actions"]
    lines.append("- Bash commands listed in your tool documentation above ONLY")
    lines.append(
        "  - Invoke a script by its PATH: `uv run scripts/<name>.py --command ...`"
        " (filename uses UNDERSCORES). The hyphenated skill name shown in listings"
        " (e.g. `context-cache`, `chat-history`) is NOT a runnable command — using"
        " it as one WILL be denied. Translate skill-name → `scripts/<name>.py`."
    )
    lines.append(
        "  - Run ONE bare command per call and read its COMPLETE output directly"
        " — the script returns exactly the data you need. Do NOT trim it"
        " (`| head`/`| jq`), suppress errors (`2>/dev/null`), or chain"
        " (`&&`/`||`/`;`): trimming drops data you need and each extra call costs"
        " time, and a chained/piped command can be denied as a whole. ONLY"
        " exception: if OpenCode itself truncates a very long result (~20k chars)"
        " into a file, `grep`/`read` THAT file for the part you need."
    )
    lines.append(f"- Read files: {'yes' if perms.read else 'no'}")

    if defn.workspace:
        resolved_ws = defn.workspace.replace("{name}", _agent_name(agent))
        lines.append(f"- Write files: only via workspace_io.py to `{resolved_ws}/`")
        lines.append(
            "- Session isolation: use `--command init` first, then pass"
            " `--run-id` to all subsequent calls"
        )
    elif perms.write:
        lines.append("- Write files: yes (unrestricted)")
    else:
        lines.append("- Write files: no")

    task_subs, bash_subs = _split_subagents(agent)
    if task_subs:
        names = ", ".join(f"`{sa.name}`" for sa in task_subs)
        lines.append(
            f"- Invoke subagents via Task tool (`subagent_type` parameter): {names}"
        )
    if bash_subs:
        names = ", ".join(f"`{sa.name}`" for sa in bash_subs)
        lines.append(
            f"- Invoke agents via bash"
            f" (`opencode_manager.py run --agent`): {names}"
        )
    if not task_subs and not bash_subs:
        lines.append("- Invoke subagents: none")

    if defn.inline_skills:
        lines.append("- Use skills: none (bash scripts are documented in prompt)")
    elif defn.skills:
        names = ", ".join(f"`{s.name}`" for s in defn.skills)
        lines.append(f"- Use skills: {names}")
    else:
        lines.append("- Use skills: none")

    lines.append("")
    return lines


def _forbidden_section(agent: AgentVariant) -> list[str]:
    defn = agent.agent_definition
    perms = _effective_permissions(agent)
    lines = ["### FORBIDDEN — You MUST NOT:"]

    if defn.workspace:
        lines.extend([
            "- Write or create files using the write/edit tools (they are disabled)",
            "- Create files via bash (no `cat >`, `echo >`, `tee`, `>`, `>>`, `touch`,"
            " `mkdir`, `cp`, `mv` or ANY other file-creating command)",
            "- Store thoughts, notes, analyses, reports, conclusions, or ANY"
            " intermediate output as files — keep everything in memory or write to"
            " your workspace via workspace_io.py ONLY",
        ])
    elif not perms.write:
        lines.extend([
            "- Write, create, or modify any files (write/edit tools are disabled)",
            "- Create files via bash (no `cat >`, `echo >`, `tee`, `>`, `>>`, `touch`,"
            " `mkdir`, `cp`, `mv` or ANY other file-creating command)",
        ])

    lines.append("- Run bash commands not listed in your tool documentation")

    if defn.inline_skills or not defn.skills:
        lines.append("- Use any skills (all skills are disabled)")
    else:
        lines.append("- Use skills other than the ones listed above")

    task_subs, bash_subs = _split_subagents(agent)
    if agent.agent_mode == "subagent" and not defn.subagents:
        lines.append(
            "- Invoke other agents via Task tool"
            " (subagents cannot delegate to other subagents)"
        )
    elif agent.agent_mode == "subagent" and defn.subagents:
        if bash_subs:
            names = ", ".join(f"`{sa.name}`" for sa in bash_subs)
            lines.append(
                f"- Invoke agents via bash"
                f" (`opencode_manager.py run --agent`): {names}"
            )
        lines.append(
            "- Invoke agents via Task tool"
            " (subagents cannot delegate to other subagents)"
        )
    elif not defn.subagents:
        lines.append("- Invoke subagents (none are configured for this agent)")
    else:
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

    if not perms.mcp:
        lines.append("- Use MCP tools (they are disabled)")

    lines.append(
        "- Create files in the project root or any directory outside your workspace"
    )
    lines.append("- Modify system files or configuration")
    lines.append("")
    return lines


def render_security_policy(agent: AgentVariant) -> str:
    parts = ["## SECURITY POLICY", ""]
    parts.extend(_allowed_section(agent))
    parts.extend(_forbidden_section(agent))
    return "\n".join(parts)
