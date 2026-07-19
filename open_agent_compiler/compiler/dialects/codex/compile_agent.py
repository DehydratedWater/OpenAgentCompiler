"""Codex agent TOML compilation.

Generates `.codex/agents/<name>.toml` files — one custom agent per file.

Codex agent TOML fields:
- `name`: Agent identifier Codex uses when spawning/referencing (required)
- `description`: When Codex should use this agent (required)
- `developer_instructions`: The agent's behavior — system prompt,
  workflow, security policy, subagent and skill docs (required)
- `model`: Model identifier (from model_parameters.model_name)
- `sandbox_mode`: `read-only` / `workspace-write`, derived from
  tool_permissions (see security_policy.derive_sandbox_mode)
- `[mcp_servers.<name>]`: MCP servers the agent may call (url-based
  servers only — stdio servers need a manual `command` entry)

TOML strings are emitted by hand (the stdlib has no TOML writer):
single-line values use JSON escaping (a valid TOML basic string),
multi-line values use `\"\"\"` basic strings with backslash and
triple-quote sequences escaped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from open_agent_compiler.compiler.dialects.codex.security_policy import (
    derive_sandbox_mode,
    render_security_policy_for_codex,
)
from open_agent_compiler.compiler.dialects.codex.workflow_renderer import render_workflow_for_codex
from open_agent_compiler.model.core.agent_model import AgentVariant


def _toml_str(value: str) -> str:
    """Escape a single-line TOML basic string (JSON escaping is a valid subset)."""
    return json.dumps(value, ensure_ascii=False)


_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(key: str) -> str:
    """Quote a TOML key unless it is a valid bare key."""
    return key if _BARE_KEY.match(key) else json.dumps(key, ensure_ascii=False)


def _toml_multiline(value: str) -> str:
    """Escape a multi-line TOML basic string.

    Backslashes are escaped first; any literal `\"\"\"` run is broken up
    with an escaped quote so the closing delimiter stays unambiguous.
    The closing delimiter goes on its own line so content may end with
    a quote character.
    """
    escaped = value.replace("\\", "\\\\").replace('"""', '""\\"')
    return f'"""\n{escaped}\n"""'


def _compose_instructions(agent: AgentVariant) -> str:
    """Build developer_instructions — mirrors the pi dialect's body."""
    defn = agent.agent_definition
    parts: list[str] = []

    if defn.header.name:
        parts.append(f"# {defn.header.name}")
        parts.append("")

    # Usage explanation — fallback body only: when the agent has a real
    # system_prompt or workflow, the long explanation would duplicate it.
    if defn.usage_explanation_long and not (defn.system_prompt or defn.workflow):
        parts.append(defn.usage_explanation_long)
        parts.append("")

    # System prompt + workflow. When workflow is set, system_prompt is
    # prepended before the workflow block.
    if defn.workflow:
        if defn.system_prompt:
            parts.append(defn.system_prompt)
            parts.append("")
        workflow_text = render_workflow_for_codex(agent)
        if workflow_text:
            parts.append(workflow_text)
    elif defn.system_prompt:
        parts.append(defn.system_prompt)
        parts.append("")

    # SECURITY POLICY
    security_policy = render_security_policy_for_codex(agent)
    if security_policy:
        parts.append(security_policy)

    # Extra tools documentation — their backing scripts are written to
    # scripts/ in the build tree, invocable from the shell.
    if defn.extra_tools:
        parts.append("## Available Tools")
        parts.append("")
        parts.append(
            "The following custom tools are available. Invoke them via the shell:"
        )
        parts.append("")
        for tool in defn.extra_tools:
            parts.append(f"### `{tool.header.name}`")
            parts.append("")
            if tool.header.description:
                parts.append(tool.header.description)
                parts.append("")
            if tool.header.usage_explanation_long:
                parts.append(tool.header.usage_explanation_long)
                parts.append("")
            if tool.bash_tool and tool.bash_tool.positive_examples:
                parts.append("**Example invocations:**")
                parts.append("")
                for example in tool.bash_tool.positive_examples:
                    parts.append(f"- `{example}`")
                parts.append("")

    # Subagent references — codex spawns subagents from natural-language
    # delegation; the custom agents referenced here are compiled as
    # sibling .toml files in .codex/agents/.
    if defn.subagents:
        parts.append("## Available Subagents")
        parts.append("")
        parts.append(
            "You can delegate work by spawning the following custom agents"
            " as subagents:"
        )
        parts.append("")
        for sub in defn.subagents:
            mode = sub.mode or "subagent"
            parts.append(
                f"- **{sub.name}** ({mode}): {sub.description or 'No description'}"
            )
        parts.append("")
        parts.append(
            f"Example: spawn the `{defn.subagents[0].name}` agent with the"
            " task description as its prompt, wait for it to finish, and"
            " use its result."
        )
        parts.append("")

    # Skills section
    if defn.skills:
        parts.append("## Your Skills")
        parts.append("")
        for skill in defn.skills:
            parts.append(f"### {skill.name}")
            parts.append("")
            parts.append(skill.usage_explanation_long)
            parts.append("")

            if skill.workflow_steps:
                parts.append("#### Workflow")
                parts.append("")
                for i, step in enumerate(skill.workflow_steps, 1):
                    parts.append(
                        f"{i}. **{step.header}** — {step.rule}"
                    )
                    if step.condition:
                        parts.append(f"   Condition: {step.condition}")
                    if step.result:
                        parts.append(f"   Result: {step.result}")
                parts.append("")

            if skill.positive_examples:
                parts.append("#### Examples")
                for ex in skill.positive_examples:
                    if ex.header:
                        parts.append(f"**{ex.header}**")
                    if ex.rule:
                        parts.append(ex.rule)
                    parts.append("")

    return "\n".join(parts).strip()


def compile_codex_agent_toml(
    target: Path,
    slot_name: str,
    postfix: str,
    agent: AgentVariant,
) -> str:
    """Compile one AgentVariant into a codex agent `.toml` file.

    Returns the generated content for testing/inspection.
    """
    defn = agent.agent_definition
    agent_name = f"{slot_name}{postfix}"

    lines: list[str] = []
    lines.append(f"name = {_toml_str(agent_name)}")

    description = defn.header.description or defn.usage_explanation_short
    lines.append(f"description = {_toml_str(description)}")

    lines.append(f"model = {_toml_str(agent.model_parameters.model_name)}")
    lines.append(f"sandbox_mode = {_toml_str(derive_sandbox_mode(agent))}")

    instructions = _compose_instructions(agent)
    lines.append(f"developer_instructions = {_toml_multiline(instructions)}")

    # MCP servers: only url-based servers can be emitted completely;
    # stdio servers (no url) need a manual `command` entry, which the
    # compiler warns about (see CodexCompiler.compile).
    for server in defn.mcp_servers:
        if not server.url:
            continue
        lines.append("")
        lines.append(f"[mcp_servers.{_toml_key(server.name)}]")
        lines.append(f"url = {_toml_str(server.url)}")

    content = "\n".join(lines) + "\n"

    agents_dir = target / ".codex" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{agent_name}.toml").write_text(content)

    return content
