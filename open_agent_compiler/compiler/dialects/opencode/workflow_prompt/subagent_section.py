"""'## Available Subagents' section listing invocable child agents.

v1 emits this between the workflow and the security policy. v2 follows
the same placement. Subagents split into two subsections based on each
header's `mode`:

- 'subagent' (default): Task-tool invocation with subagent_type.
- 'primary': bash invocation via opencode_manager.py.
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentHeader, AgentVariant


def _effective_mode(sa: AgentHeader) -> str:
    return sa.mode or "subagent"


def _render_task_subagents(headers: list[AgentHeader]) -> list[str]:
    out = [
        "Invoke subagents using the **Task tool** with the `subagent_type`"
        " parameter set to the agent name shown below.",
        "",
    ]
    for sa in headers:
        out.append(
            f"### {sa.name} — {sa.description or 'no description'}"
        )
        out.append("")
        out.append(
            f'Task tool call: `subagent_type: "{sa.name}"`,'
            f' `prompt: "<your instructions>"`'
        )
        out.append("")
    return out


def _render_bash_subagents(headers: list[AgentHeader]) -> list[str]:
    out = [
        "Invoke the following agents using `opencode_manager.py` via the"
        " **bash** tool. These are standalone primary agents.",
        "",
    ]
    for sa in headers:
        out.append(
            f"### {sa.name} — {sa.description or 'no description'}"
        )
        out.append("")
        out.append("```bash")
        out.append(
            f"uv run scripts/opencode_manager.py run --agent {sa.name}"
            " <your instructions>"
        )
        out.append("```")
        out.append("")
    return out


def render_subagent_section(agent: AgentVariant) -> str:
    subagents = agent.agent_definition.subagents
    if not subagents:
        return ""
    task_subs = [s for s in subagents if _effective_mode(s) == "subagent"]
    bash_subs = [s for s in subagents if _effective_mode(s) == "primary"]
    parts: list[str] = ["## Available Subagents", ""]
    if task_subs:
        parts.extend(_render_task_subagents(task_subs))
    if bash_subs:
        parts.extend(_render_bash_subagents(bash_subs))
    return "\n".join(parts)
