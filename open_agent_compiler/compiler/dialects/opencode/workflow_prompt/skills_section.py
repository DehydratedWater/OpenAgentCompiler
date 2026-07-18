"""Per-agent skills section, emitted into the workflow prompt body.

Two formats, picked by AgentDefinition.inline_skills:

- False (reference): "## Your Skills (use via bash)" with name + tool
  names listed per skill. Compact — fits agents that already have a
  separate SKILL.md (Phase 4 will land that writer) and just need the
  model to know which skill names exist.

- True (inline): "## Available Bash Scripts" with full bash command
  syntax per tool. Heavier — used when the agent has no companion
  SKILL.md and needs the action docs in-prompt.

This mirrors v1's _compile_workflow_prompt skill-section branches
(compiler.py:492-519).
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentVariant
from open_agent_compiler.model.core.skills_model import SkillDefinition
from open_agent_compiler.model.core.tools_model import ToolDefinition


def _gather_skill_tools(skill: SkillDefinition) -> list[ToolDefinition]:
    """De-duped list of tools mentioned across this skill's workflow_steps."""
    seen: dict[str, ToolDefinition] = {}
    for step in skill.workflow_steps:
        for tool in step.tools_used:
            seen.setdefault(tool.header.name, tool)
    return list(seen.values())


def _render_inline_tool(tool: ToolDefinition) -> list[str]:
    """Full action docs for one tool: bash command syntax + examples."""
    parts: list[str] = [f"#### `{tool.header.name}` — {tool.header.description}"]
    if tool.header.usage_explanation_long:
        parts.append(tool.header.usage_explanation_long)
        parts.append("")
    if tool.bash_tool and tool.bash_tool.positive_examples:
        parts.append("Examples:")
        parts.append("```bash")
        for ex in tool.bash_tool.positive_examples:
            parts.append(ex)
        parts.append("```")
        parts.append("")
    return parts


def render_skills_section(agent: AgentVariant) -> str:
    defn = agent.agent_definition
    if not defn.skills:
        return ""

    parts: list[str] = []
    if defn.inline_skills:
        parts.append("## Available Bash Scripts")
        parts.append("")
        parts.append(
            "**IMPORTANT:** These are NOT callable tools. To use them, run the"
            " bash commands shown below using the `bash` tool."
        )
        parts.append("")
        for skill in defn.skills:
            parts.append(f"### {skill.description}")
            if skill.usage_explanation_long:
                parts.append(skill.usage_explanation_long)
            parts.append("")
            for tool in _gather_skill_tools(skill):
                parts.extend(_render_inline_tool(tool))
    else:
        parts.append("## Your Skills (use via bash)")
        parts.append("")
        for skill in defn.skills:
            parts.append(f"### {skill.description}")
            if skill.usage_explanation_long:
                parts.append(skill.usage_explanation_long)
            tools = _gather_skill_tools(skill)
            if tools:
                tool_names = ", ".join(f"`{t.header.name}`" for t in tools)
                parts.append(f"Tools: {tool_names}")
            parts.append("")
    return "\n".join(parts)
