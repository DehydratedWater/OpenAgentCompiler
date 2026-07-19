"""SECURITY POLICY block for codex agent instructions.

Mirrors pi's security_policy.py but adapted for Codex's model:
- Codex has no per-agent tool allowlist; filesystem/network boundaries
  come from `sandbox_mode` in the agent TOML. The SECURITY POLICY block
  makes the intended constraints visible to the agent so the prompt and
  the sandbox stay in sync.
- Subagents are spawned by asking Codex to delegate, not via a spawn
  tool, so delegation rules are phrased in natural language.

The block is emitted when:
- The agent has a workflow (needs to understand tool boundaries)
- The agent has subagents (needs to understand delegation rules)
- The agent has explicit tool_permissions (needs to understand denials)
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentVariant, ToolPermissions


def _effective_permissions(agent: AgentVariant) -> ToolPermissions:
    return agent.agent_definition.tool_permissions or ToolPermissions()


def derive_sandbox_mode(agent: AgentVariant) -> str:
    """Map tool_permissions onto Codex's sandbox_mode.

    None (unset) keeps Codex's workspace-write default — mirrors the pi
    dialect's permissive default. Explicit permissions with neither
    write nor edit collapse to read-only; any mutating toggle needs
    workspace-write.
    """
    perms = agent.agent_definition.tool_permissions
    if perms is None:
        return "workspace-write"
    if perms.write or perms.edit:
        return "workspace-write"
    return "read-only"


def render_security_policy_for_codex(agent: AgentVariant) -> str:
    """Render a SECURITY POLICY block for the codex developer_instructions.

    Returns empty string when no policy is needed (no workflow, no
    subagents, no explicit permissions).
    """
    defn = agent.agent_definition
    perms = _effective_permissions(agent)
    has_workflow = bool(defn.workflow)
    has_subagents = bool(defn.subagents)
    permissions_explicit = defn.tool_permissions is not None

    if not (has_workflow or has_subagents or permissions_explicit):
        return ""

    sandbox_mode = derive_sandbox_mode(agent)

    parts: list[str] = ["## SECURITY POLICY", ""]

    # ALLOWED section
    parts.append("### ALLOWED actions")
    parts.append(
        f"- Operate within your sandbox (`sandbox_mode = {sandbox_mode}`)"
    )
    if has_subagents:
        names = ", ".join(f"`{sa.name}`" for sa in defn.subagents)
        parts.append(f"- Delegate work by spawning subagents: {names}")
    if defn.skills:
        names = ", ".join(f"`{s.name}`" for s in defn.skills)
        parts.append(f"- Use skills: {names}")
    parts.append("")

    # FORBIDDEN section
    parts.append("### FORBIDDEN — You MUST NOT:")
    if permissions_explicit:
        if not perms.read:
            parts.append("- Read files outside what the task explicitly requires")
        if not perms.write:
            parts.append("- Write or create files (write access is disabled)")
        if not perms.edit:
            parts.append("- Edit files (edit access is disabled)")
        if not perms.mcp:
            parts.append("- Use MCP tools (they are disabled)")
    if not has_subagents:
        parts.append("- Spawn subagents (none are configured for this agent)")
    elif agent.agent_mode == "subagent":
        parts.append("- Spawn subagents (subagents cannot delegate to other subagents)")
    parts.append("- Escape or work around your sandbox restrictions")
    parts.append("")

    return "\n".join(parts)
