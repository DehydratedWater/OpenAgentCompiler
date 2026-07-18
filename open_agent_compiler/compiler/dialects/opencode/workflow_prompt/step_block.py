"""Render one WorkflowStepDefinition into the system-prompt markdown."""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.todo_block import render_mark_done
from open_agent_compiler.model.core.agent_model import AgentVariant
from open_agent_compiler.model.core.workflow_model import (
    Criterion,
    Gate,
    Route,
    ToolUse,
    WorkflowStepDefinition,
)


def _gate_block(gate: Gate) -> list[str]:
    out: list[str] = []
    if len(gate.checks) == 1:
        c = gate.checks[0]
        out.append(f"**Condition:** Only execute if `{c.variable}` = `{c.value}`")
    elif gate.logic == "all":
        out.append("**Condition (ALL must be true):**")
        for c in gate.checks:
            out.append(f"- `{c.variable}` = `{c.value}`")
    else:
        out.append("**Condition (ANY must be true):**")
        for c in gate.checks:
            out.append(f"- `{c.variable}` = `{c.value}`")
    out.append("If condition is not met, skip this step.")
    out.append("")
    return out


def _criteria_block(evaluates: tuple[Criterion, ...]) -> list[str]:
    if not evaluates:
        return []
    out = ["**Evaluate the following criteria:**"]
    for crit in evaluates:
        out.append(f"- **{crit.name}**: {crit.question}")
        if crit.possible_values:
            vals = " | ".join(f"`{v}`" for v in crit.possible_values)
            out.append(f"  Possible values: {vals}")
    out.append("")
    return out


def _tool_uses_block(tool_uses: tuple[ToolUse, ...]) -> list[str]:
    if not tool_uses:
        return []
    out = ["**Use these tools:**"]
    for u in tool_uses:
        line = f"- `{u.tool_name}`"
        if u.note:
            line += f" — {u.note}"
        out.append(line)
    out.append("")
    return out


def _subagent_invocations(
    step: WorkflowStepDefinition, agent: AgentVariant
) -> list[str]:
    """Generate per-subagent invocation snippets, picking mode from agent.subagents."""
    if not step.subagents:
        return []
    # Map subagent agent_id → mode lookup, falling back to "subagent".
    # Agent v2 model uses AgentHeader (no mode field) for subagents, so
    # the mode comes from the referenced agent's own variant when available.
    # Until we wire that up the mode lookup defaults to "subagent" — Phase 4
    # will refine this when bundled spawn scripts land.
    out: list[str] = []
    for sa_name in step.subagents:
        out.append(f"**Invoke `{sa_name}` via Task tool:**")
        out.append(
            f'`subagent_type: "{sa_name}"`, `prompt: "<your instructions>"`'
        )
        out.append("")
    return out


def _routes_block(routes: tuple[Route, ...]) -> list[str]:
    if not routes:
        return []
    out = ["**Based on evaluation, route to:**"]
    for r in routes:
        out.append(
            f"- If `{r.criteria_name}` = `{r.value}` → Go to **STEP {r.goto_step}**"
        )
    out.append("")
    return out


def render_step(step: WorkflowStepDefinition, agent: AgentVariant) -> str:
    """Render a single workflow step block (between --- dividers)."""
    parts: list[str] = [f"### STEP {step.id}: {step.name}", ""]
    if step.gate is not None:
        parts.extend(_gate_block(step.gate))
    parts.extend(_tool_uses_block(step.tool_uses))
    parts.extend(_criteria_block(step.evaluates))
    if step.instructions:
        parts.append(step.instructions)
        parts.append("")
    parts.extend(_subagent_invocations(step, agent))
    mark_done = render_mark_done(agent, step.marks_done)
    if mark_done:
        parts.append(mark_done)
    parts.extend(_routes_block(step.routes))
    parts.append("---")
    parts.append("")
    return "\n".join(parts)
