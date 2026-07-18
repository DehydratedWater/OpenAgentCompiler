"""Render the *interactive* system prompt for an AgentDefinition.

This is deliberately NOT the opencode prompt. The opencode renderers emit
bash-invocation syntax, a todo/STEP-0 block, a permission/security policy,
and subagent-dispatch instructions — all scaffolding for the opencode
runtime. In the interactive target, tools are bound *natively* (the model
receives tool schemas and calls them directly), so that scaffolding is
noise. We render only the agent's CORE intent:

  system prompt (or usage explanation) + the workflow as plain guidance +
  the skills as described capabilities.

The same `AgentDefinition` therefore yields a worker prompt (opencode) and a
leaner interactive prompt, from one source.
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentDefinition
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition


def _render_workflow_guidance(workflow: list[WorkflowStepDefinition]) -> str:
    lines = ["## How to approach this", ""]
    for i, step in enumerate(workflow, 1):
        name = getattr(step, "name", None) or getattr(step, "header", None) or f"Step {i}"
        lines.append(f"{i}. **{name}**")
        desc = getattr(step, "description", None) or getattr(step, "result", None)
        if desc:
            lines.append(f"   {desc}")
        cond = getattr(step, "condition", None)
        if cond:
            lines.append(f"   (when: {cond})")
    return "\n".join(lines)


def _render_skills_capabilities(skills) -> str:
    lines = ["## Capabilities available to you", ""]
    for sk in skills:
        name = getattr(sk, "name", None) or getattr(getattr(sk, "header", None), "name", "skill")
        desc = (
            getattr(sk, "description", None)
            or getattr(sk, "usage_explanation_short", None)
            or ""
        )
        lines.append(f"- **{name}** — {desc}".rstrip(" —"))
    return "\n".join(lines)


def render_interactive_prompt(agent: AgentDefinition) -> str:
    """Compose the interactive system prompt from the agent's core fields."""
    parts: list[str] = []

    base = agent.system_prompt or agent.usage_explanation_long or ""
    if base.strip():
        parts.append(base.strip())

    if agent.preamble.strip():
        parts.append(agent.preamble.strip())

    if agent.workflow:
        parts.append(_render_workflow_guidance(agent.workflow))

    if agent.skills:
        parts.append(_render_skills_capabilities(agent.skills))

    if agent.postamble.strip():
        parts.append(agent.postamble.strip())

    return "\n\n".join(parts).strip()
