"""Pi agent markdown compilation.

Generates `.pi/agents/<name>.md` files with YAML frontmatter and a
markdown body containing the system prompt.

Pi agent frontmatter fields:
- `description`: Short description (from agent_definition.header.description)
- `tools`: Comma-separated list of allowed tools (mapped from permissions + extra_tools)
- `model`: Model identifier (from model_parameters.model_name)
- `thinking`: Thinking level (off, minimal, low, medium, high, xhigh)
- `max_turns`: Maximum agentic turns (optional)
- `skills`: Comma-separated skill names (from agent_definition.skills)
- `memory`: Persistent memory scope (project, local, user)
- `disallowed_tools`: Tools to explicitly deny
- `prompt_mode`: `replace` (standalone prompt) or `append` (inherit parent prompt)
- `extensions`: Which extensions to load (default true)
- `isolation`: `worktree` for git worktree isolation

The body is the agent's system prompt, which may include:
- Custom system_prompt text
- Rendered workflow (MANDATORY WORKFLOW)
- Subagent references
- Skills documentation
"""

from __future__ import annotations

from pathlib import Path

import yaml

from open_agent_compiler.compiler.dialects.pi_agent.security_policy import render_security_policy_for_pi
from open_agent_compiler.compiler.dialects.pi_agent.tool_mapping import map_tools_for_pi
from open_agent_compiler.compiler.dialects.pi_agent.workflow_renderer import render_workflow_for_pi
from open_agent_compiler.model.core.agent_model import AgentVariant


def compile_pi_agent_markdown(
    target: Path,
    slot_name: str,
    postfix: str,
    agent: AgentVariant,
) -> str:
    """Compile one AgentVariant into a pi agent `.md` file.

    Returns the generated content for testing/inspection.
    """
    defn = agent.agent_definition

    # Build frontmatter
    frontmatter: dict = {}

    # Description
    if defn.header.description:
        frontmatter["description"] = defn.header.description

    # Model
    frontmatter["model"] = agent.model_parameters.model_name

    # Tools: map from OAC tool model to pi tool names
    tools_list, disallowed_list = map_tools_for_pi(agent)
    if tools_list:
        frontmatter["tools"] = ", ".join(tools_list)
    if disallowed_list:
        frontmatter["disallowed_tools"] = ", ".join(disallowed_list)

    # Skills: extract skill names
    if defn.skills:
        skill_names = [skill.name for skill in defn.skills]
        frontmatter["skills"] = ", ".join(skill_names)

    # Thinking level: derive from model_parameters or default
    # For now, we don't have a thinking level in the OAC model, so we omit it
    # Users can add it via prompt_sections or custom fields if needed

    # Max turns: not in OAC model, omit by default
    # Users can set this in pi agent config

    # Memory: not in OAC model, omit by default

    # Disallowed tools are now computed in map_tools_for_pi and returned
    # as the second element of the tuple (see P1#3 fix).

    # Prompt mode: pi agents are standalone by default
    frontmatter["prompt_mode"] = "replace"

    # Build body
    body_parts: list[str] = []

    # Header
    if defn.header.name:
        body_parts.append(f"# {defn.header.name}")
        body_parts.append("")

    # Description (if not in frontmatter)
    if defn.header.description and "description" not in frontmatter:
        body_parts.append(defn.header.description)
        body_parts.append("")

    # Usage explanation — fallback body only, mirroring opencode's
    # compose_body: when the agent has a real system_prompt or workflow,
    # the long explanation would just duplicate content.
    if defn.usage_explanation_long and not (defn.system_prompt or defn.workflow):
        body_parts.append(defn.usage_explanation_long)
        body_parts.append("")

    # System prompt + workflow
    # When workflow is set, system_prompt is prepended before the workflow
    # block (mirrors opencode's compose_body and the AgentDefinition docstring).
    if defn.workflow:
        if defn.system_prompt:
            body_parts.append(defn.system_prompt)
            body_parts.append("")
        workflow_text = render_workflow_for_pi(agent)
        if workflow_text:
            body_parts.append(workflow_text)
    elif defn.system_prompt:
        body_parts.append(defn.system_prompt)
        body_parts.append("")

    # SECURITY POLICY
    security_policy = render_security_policy_for_pi(agent)
    if security_policy:
        body_parts.append(security_policy)

    # Extra tools documentation
    if defn.extra_tools:
        body_parts.append("## Available Tools")
        body_parts.append("")
        body_parts.append(
            "The following custom tools are available. Invoke them via bash:"
        )
        body_parts.append("")
        for tool in defn.extra_tools:
            body_parts.append(f"### `{tool.header.name}`")
            body_parts.append("")
            if tool.header.description:
                body_parts.append(tool.header.description)
                body_parts.append("")
            if tool.header.usage_explanation_long:
                body_parts.append(tool.header.usage_explanation_long)
                body_parts.append("")
            if tool.bash_tool and tool.bash_tool.positive_examples:
                body_parts.append("**Example invocations:**")
                body_parts.append("")
                for example in tool.bash_tool.positive_examples:
                    body_parts.append(f"- `{example}`")
                body_parts.append("")

    # Subagent references
    if defn.subagents:
        body_parts.append("## Available Subagents")
        body_parts.append("")
        body_parts.append(
            "You can spawn the following subagents using the `Agent()` tool:"
        )
        body_parts.append("")
        for sub in defn.subagents:
            mode = sub.mode or "subagent"
            body_parts.append(
                f"- **{sub.name}** ({mode}): {sub.description or 'No description'}"
            )
        body_parts.append("")
        body_parts.append(
            'Example: `Agent({ "subagent_type": "'
            + defn.subagents[0].name
            + '", "prompt": "<task>", "description": "<short desc>" })`'
        )
        body_parts.append("")

    # Skills section
    if defn.skills:
        body_parts.append("## Your Skills")
        body_parts.append("")
        for skill in defn.skills:
            body_parts.append(f"### {skill.name}")
            body_parts.append("")
            body_parts.append(skill.usage_explanation_long)
            body_parts.append("")

            if skill.workflow_steps:
                body_parts.append("#### Workflow")
                body_parts.append("")
                for i, step in enumerate(skill.workflow_steps, 1):
                    body_parts.append(
                        f"{i}. **{step.header}** — {step.rule}"
                    )
                    if step.condition:
                        body_parts.append(f"   Condition: {step.condition}")
                    if step.result:
                        body_parts.append(f"   Result: {step.result}")
                body_parts.append("")

            if skill.positive_examples:
                body_parts.append("#### Examples")
                for ex in skill.positive_examples:
                    if ex.header:
                        body_parts.append(f"**{ex.header}**")
                    if ex.rule:
                        body_parts.append(ex.rule)
                    body_parts.append("")

    content_parts: list[str] = []

    # YAML frontmatter
    if frontmatter:
        content_parts.append("---")
        content_parts.append(
            yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
        )
        content_parts.append("---")
        content_parts.append("")

    # Body
    content_parts.extend(body_parts)

    content = "\n".join(content_parts)

    # Write to .pi/agents/<slot_name><postfix>.md
    agent_name = f"{slot_name}{postfix}"
    agents_dir = target / ".pi" / "agents"
    file_path = agents_dir / f"{agent_name}.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

    return content
