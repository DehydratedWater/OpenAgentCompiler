"""Compose the agent's body content from system_prompt + workflow.

Rules (mirroring v1):
- Workflow set: body = system_prompt (if any) + WorkflowPromptBuilder.render().
- Workflow empty + system_prompt set: body = system_prompt.
- Workflow empty + system_prompt empty: body = usage_explanation_long
  (backward-compat with v2's pre-Phase-3 behavior).

Returned string is the full body block — callers prepend the agent
title/description and append skills/subagent/security sections.
"""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.builder import (
    WorkflowPromptBuilder,
)
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.security_policy import (
    render_security_policy,
)
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.subagent_section import (
    render_subagent_section,
)
from open_agent_compiler.model.core.agent_model import AgentVariant


def compose_body(agent: AgentVariant) -> str:
    defn = agent.agent_definition
    has_workflow = bool(defn.workflow)

    if has_workflow:
        workflow_text = WorkflowPromptBuilder().render(agent)
        body = (
            f"{defn.system_prompt}\n\n{workflow_text}"
            if defn.system_prompt else workflow_text
        )
    elif defn.system_prompt:
        body = defn.system_prompt
    else:
        body = defn.usage_explanation_long

    # Available Subagents + SECURITY POLICY are emitted in every workflow
    # agent's prompt and also when a non-workflow agent declares subagents
    # or non-default tool permissions — same trigger as v1.
    suffix_parts: list[str] = []
    sub_section = render_subagent_section(agent)
    if sub_section:
        suffix_parts.append(sub_section)
    needs_policy = has_workflow or defn.subagents or defn.tool_permissions
    if needs_policy:
        suffix_parts.append(render_security_policy(agent))

    if not suffix_parts:
        return body
    if not body:
        return "\n\n".join(suffix_parts)
    return body + "\n\n" + "\n\n".join(suffix_parts)
