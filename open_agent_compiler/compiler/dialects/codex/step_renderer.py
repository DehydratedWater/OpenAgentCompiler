"""Render individual workflow steps for codex agent instructions.

Each workflow step becomes a markdown section with:
- Step name as heading
- Instructions
- Gate conditions (if any)
- Tool usage notes
- Subagent references (natural-language delegation — Codex has no
  explicit spawn tool; it orchestrates spawning when asked)
- Routes (conditional jumps)
"""

from __future__ import annotations

from open_agent_compiler.model.core.agent_model import AgentVariant
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition


def render_step_for_codex(step: WorkflowStepDefinition, agent: AgentVariant) -> str:
    """Render one workflow step as markdown.

    Returns the rendered step text.
    """
    parts: list[str] = []

    # Step header
    parts.append(f"### Step {step.id}: {step.name}")
    parts.append("")

    # Gate condition
    if step.gate:
        parts.append("**Condition:**")
        parts.append("")
        if step.gate.logic == "all":
            parts.append("Execute this step ONLY if ALL of the following are true:")
        else:
            parts.append("Execute this step if ANY of the following are true:")
        parts.append("")
        for check in step.gate.checks:
            parts.append(f"- `{check.variable}` = `{check.value}`")
        parts.append("")

    # Evaluation criteria — routes reference these by name, so the agent
    # must be told what to evaluate before it can route.
    if step.evaluates:
        parts.append("**Evaluate the following criteria:**")
        parts.append("")
        for crit in step.evaluates:
            parts.append(f"- **{crit.name}**: {crit.question}")
            if crit.possible_values:
                vals = " | ".join(f"`{v}`" for v in crit.possible_values)
                parts.append(f"  Possible values: {vals}")
        parts.append("")

    # Instructions
    if step.instructions:
        parts.append(step.instructions)
        parts.append("")

    # Tool usage
    if step.tool_uses:
        parts.append("**Tools to use:**")
        parts.append("")
        for tool_use in step.tool_uses:
            note = f" — {tool_use.note}" if tool_use.note else ""
            parts.append(f"- `{tool_use.tool_name}`{note}")
        parts.append("")

    # Subagent references
    if step.subagents:
        parts.append("**Subagents to spawn:**")
        parts.append("")
        for sub_name in step.subagents:
            # Find the subagent definition
            sub_def = None
            for sub in agent.agent_definition.subagents:
                if sub.name == sub_name:
                    sub_def = sub
                    break
            if sub_def:
                desc = sub_def.description or sub_name
                parts.append(
                    f"- Spawn the `{sub_name}` agent as a subagent"
                    f" ({desc}) with the task description as its prompt,"
                    " then wait for its result"
                )
            else:
                parts.append(f"- Spawn `{sub_name}` (definition not found in this agent)")
        parts.append("")

    # Routes (conditional jumps)
    if step.routes:
        parts.append("**Conditional routes:**")
        parts.append("")
        for route in step.routes:
            parts.append(
                f"- If `{route.criteria_name}` = `{route.value}`, jump to Step {route.goto_step}"
            )
        parts.append("")

    # Marks done (todo tracking) — only meaningful when the agent was
    # told to keep a todo list at all.
    if step.marks_done and agent.agent_definition.todo_mode != "none":
        parts.append("**After finishing this step, mark as complete in your TODO.md:**")
        parts.append("")
        for todo_name in step.marks_done:
            parts.append(f"- [ ] {todo_name}")
        parts.append("")

    return "\n".join(parts)
