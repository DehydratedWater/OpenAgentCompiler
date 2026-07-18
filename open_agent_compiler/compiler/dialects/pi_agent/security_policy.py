"""SECURITY POLICY block for pi agent prompts.

Mirrors opencode's security_policy.py but adapted for pi's format:
- pi agents don't have a separate permission block — security is enforced
  via the tools allowlist in frontmatter + explicit disallowed_tools.
- The SECURITY POLICY block in the body makes these constraints visible
  to the agent so it understands what it can and cannot do.

The block is emitted when:
- The agent has a workflow (needs to understand tool boundaries)
- The agent has subagents (needs to understand delegation rules)
- The agent has explicit tool_permissions (needs to understand denials)
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentVariant, ToolPermissions


def _effective_permissions(agent: AgentVariant) -> ToolPermissions:
    return agent.agent_definition.tool_permissions or ToolPermissions()


# NOTE: unlike opencode (where primary-mode subagents are invoked via the
# bundled opencode_manager.py bash script), pi has a single spawning
# mechanism — the Agent() tool from pi-subagents. All subagents are
# therefore listed under Agent() regardless of their declared mode.


def render_security_policy_for_pi(agent: AgentVariant) -> str:
    """Render a SECURITY POLICY block for the pi agent body.

    Returns empty string when no policy is needed (no workflow, no subagents,
    no explicit permissions).
    """
    defn = agent.agent_definition
    perms = _effective_permissions(agent)
    has_workflow = bool(defn.workflow)
    has_subagents = bool(defn.subagents)
    permissions_explicit = defn.tool_permissions is not None

    if not (has_workflow or has_subagents or permissions_explicit):
        return ""

    parts: list[str] = ["## SECURITY POLICY", ""]

    # ALLOWED section
    parts.append("### ALLOWED actions")
    parts.append("- Use tools listed in your frontmatter `tools` field")
    if has_subagents:
        names = ", ".join(
            f"`{sa.name}`" for sa in defn.subagents
        )
        parts.append(f"- Spawn subagents via Agent() tool: {names}")
    if defn.skills:
        names = ", ".join(f"`{s.name}`" for s in defn.skills)
        parts.append(f"- Use skills: {names}")
    parts.append("")

    # FORBIDDEN section
    parts.append("### FORBIDDEN — You MUST NOT:")
    if permissions_explicit:
        if not perms.read:
            parts.append("- Read files (read tool is disabled)")
        if not perms.write:
            parts.append("- Write or create files (write tool is disabled)")
        if not perms.edit:
            parts.append("- Edit files (edit tool is disabled)")
        if not perms.mcp:
            parts.append("- Use MCP tools (they are disabled)")
    if not has_subagents:
        parts.append("- Spawn subagents (none are configured for this agent)")
    elif agent.agent_mode == "subagent":
        parts.append("- Spawn subagents (subagents cannot delegate to other subagents)")
    parts.append("- Use tools not listed in your frontmatter `tools` field")
    parts.append("")

    return "\n".join(parts)
