"""Render OAC workflow definitions for codex agent instructions.

Codex agents receive their behavior through `developer_instructions` in
the agent TOML. When an agent has a workflow defined, we render it as
markdown sections the agent follows.

This mirrors the pi workflow renderer:
- No `## MANDATORY WORKFLOW` header framing
- Todo tracking via TODO.md file conventions (codex has no todo tools)
- Subagent references use natural-language delegation (codex has no
  explicit spawn tool)

The rendered workflow becomes part of the agent's developer_instructions.
"""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.codex.step_renderer import render_step_for_codex
from open_agent_compiler.model.core.agent_model import AgentVariant


def render_workflow_for_codex(agent: AgentVariant) -> str:
    """Render an AgentVariant's workflow as markdown for the codex body.

    Returns empty string when the agent has no workflow.
    """
    defn = agent.agent_definition
    if not defn.workflow:
        return ""

    parts: list[str] = []

    # Preamble (if any)
    if defn.preamble:
        parts.append(defn.preamble)
        parts.append("")

    # Workflow header
    parts.append("## Workflow")
    parts.append("")
    parts.append("Follow these steps for every incoming task:")
    parts.append("")

    # Todo mode note. Codex has no todoread/todowrite tools, so both
    # modes use a TODO.md file — strict adds an explicit STEP 0 and
    # per-step update discipline, lazy is a lightweight reminder.
    if defn.todo_mode == "strict":
        parts.append(
            "**STEP 0 (before anything else): create a `TODO.md` file"
            " listing every workflow step below as an unchecked item."
            " After completing each step, immediately mark it done in"
            " `TODO.md`. Never skip this bookkeeping.**"
        )
        parts.append("")
    elif defn.todo_mode != "none":
        parts.append(
            "**Track your progress by maintaining a todo list in your"
            " workspace (e.g. a TODO.md file).**"
        )
        parts.append("")

    # Critical instruction
    parts.append(
        "CRITICAL: YOU MUST EXECUTE ALL STEPS WITHOUT ANY USER INPUT."
        " DO NOT STOP UNTIL YOU FINISH ALL STEPS."
    )
    parts.append("")
    parts.append("---")
    parts.append("")

    # Workspace init (if workspace is set)
    if defn.workspace:
        workspace_name = defn.workspace.replace("{name}", defn.header.name)
        parts.append("### Initialize Workspace")
        parts.append("")
        parts.append(
            f"Create and use the workspace directory: `{workspace_name}`"
        )
        parts.append("")

    # Steps
    for step in defn.workflow:
        parts.append(render_step_for_codex(step, agent))

    # Final checklist
    parts.append("## Final Checklist")
    parts.append("")
    parts.append("Before submitting your final answer:")
    parts.append("")
    parts.append("- [ ] All workflow steps completed")
    parts.append("- [ ] Output matches the requested format")
    parts.append("- [ ] No steps skipped")
    parts.append("")

    # Postamble
    if defn.postamble:
        parts.append(defn.postamble)
        parts.append("")

    return "\n".join(parts)
