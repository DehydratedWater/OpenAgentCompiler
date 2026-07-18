"""'## FINAL CHECKLIST - Before You Finish' block at the end of the workflow."""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.todo_block import (
    render_strict_verification,
)
from open_agent_compiler.model.core.agent_model import AgentVariant


def _unique_todo_items(agent: AgentVariant) -> list[str]:
    """Stable de-dup of step todo names, first occurrence wins."""
    seen: set[str] = set()
    out: list[str] = []
    for step in agent.agent_definition.workflow:
        name = step.effective_todo_name()
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def render_final_checklist(agent: AgentVariant) -> str:
    """Render the final checklist block.

    Under strict todo_mode, a verification command (subagent_todo.py
    list / todoread) is prepended so the agent confirms completion
    before exiting.
    """
    items = _unique_todo_items(agent)
    parts = ["## FINAL CHECKLIST - Before You Finish", ""]
    verification = render_strict_verification(agent)
    if verification:
        parts.append(verification)
    if items:
        parts.append("**ASK YOURSELF:**")
        for name in items:
            parts.append(f'- ✅ Did I complete "{name}"?')
        parts.append("")
    return "\n".join(parts)
