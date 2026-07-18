"""WorkflowPromptBuilder — compose per-concern renderers into one prompt.

Phase 3.1 lands the skeleton: MANDATORY WORKFLOW header + per-step
blocks + final checklist. Subsequent phases bolt on:
- 3.2 todo_block (STEP 0 + per-step mark-done)
- 3.3 inline_skills section
- 3.4 preamble / postamble / system_prompt composition
- 3.5 SECURITY POLICY + Available Subagents

Each concern lives in its own module so it stays testable in isolation.
The builder is intentionally not a class with mutable state — it's a
pure function composition over a frozen AgentVariant + flags.
"""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.final_checklist import (
    render_final_checklist,
)
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.skills_section import (
    render_skills_section,
)
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.step_block import render_step
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.todo_block import (
    render_todo_step_0,
    render_workspace_init,
)
from open_agent_compiler.model.core.agent_model import AgentVariant


class WorkflowPromptBuilder:
    """Render an AgentVariant's MANDATORY WORKFLOW to system-prompt markdown.

    Returns an empty string when the agent has no workflow steps —
    callers (the compiler) can then fall back to a static system_prompt.
    """

    def render(self, agent: AgentVariant) -> str:
        defn = agent.agent_definition
        if not defn.workflow:
            return ""

        is_subagent = agent.agent_mode == "subagent"
        parts: list[str] = []

        # Preamble lives before the MANDATORY WORKFLOW header so authors
        # can frame the workflow ("# Orchestration Overview\n…") without
        # editing the header text itself.
        if defn.preamble:
            parts.append(defn.preamble)
            parts.append("")

        # Skills section sits between preamble and the workflow header so
        # the model sees what's available before it's told to follow the
        # mandatory procedure.
        skills_text = render_skills_section(agent)
        if skills_text:
            parts.append(skills_text)

        header_lines = [
            "## MANDATORY WORKFLOW",
            "",
            "Follow these steps for EVERY incoming message.",
        ]
        if defn.todo_mode != "none":
            if is_subagent:
                header_lines.append("**Use `subagent_todo.py` to track your progress!**")
            else:
                header_lines.append(
                    "**Use todowrite and todoread tools to track your progress!**"
                )
        header_lines.extend([
            "",
            "CRITICAL: YOU MUST EXECUTE ALL POINTS WITHOUT ANY USER INPUT,",
            (
                "DO NOT STOP UNTIL YOU FINISHED ALL STEPS"
                + (" FROM YOUR TODO LIST" if defn.todo_mode != "none" else "")
            ),
            "",
            "---",
            "",
        ])
        parts.extend(header_lines)

        workspace_block = render_workspace_init(agent)
        if workspace_block:
            parts.append(workspace_block)
        todo_block = render_todo_step_0(agent)
        if todo_block:
            parts.append(todo_block)
        for step in defn.workflow:
            parts.append(render_step(step, agent))
        parts.append(render_final_checklist(agent))
        # Postamble closes out the prompt after the final checklist.
        if defn.postamble:
            parts.append(defn.postamble)
            parts.append("")
        return "\n".join(p for p in parts if p is not None)
