"""Structural mutators — evolve the agent's SHAPE, not just its prompt text.

Prompt rewriting finds better phrasings of the same behavior; these
mutators change what the agent IS: its workflow steps, its tool
surface. That's how an autoloop discovers "the agent should verify
after every edit" (a new step) or "this tool is dead weight" (a
removal) — improvements no prompt mutation can express.

Deterministic mutators let a loop author propose specific structural
hypotheses; `LLMWorkflowEditor` lets the LLM propose the structure
itself (returning a full edited workflow, validated before acceptance).
All operate on the candidate's definition dict — the loop's universal
currency — so criteria, snapshots, per-target promotion, and
`apply_promoted_to_agent` (whose merged fields include prompt-adjacent
structure) work unchanged. Your `registry_factory` / registry override
hook must apply the mutated fields when rebuilding candidates (the
evolve harness loader does).
"""

from __future__ import annotations

import json
from typing import Any

from open_agent_compiler.improvement.mutators.base import Mutator, MutationContext
from open_agent_compiler.improvement.version import ComponentVersion


def _child(
    version: ComponentVersion, definition: dict[str, Any], author: str,
) -> ComponentVersion:
    return ComponentVersion.of(
        component_id=version.component_id, kind=version.kind,
        definition=definition, parent_hash=version.content_hash,
        author=author,
    )


def _renumber(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**step, "id": i} for i, step in enumerate(steps, 1)]


class WorkflowStepAppendMutator(Mutator):
    """Insert a candidate workflow step (at `position`, default: append).

    `step` is a WorkflowStepDefinition-shaped dict; `id` is assigned by
    renumbering. Skips agents without a workflow list and no-ops when a
    step with the same name already exists (idempotent across rounds).
    """

    name = "workflow-step-append"

    def __init__(
        self, step: dict[str, Any], *,
        position: int | None = None, name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"workflow-step-append:{step.get('name')}")
        self.step = dict(step)
        self.position = position

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        workflow = [dict(s) for s in (defn.get("workflow") or [])]
        if any(s.get("name") == self.step.get("name") for s in workflow):
            return None
        index = len(workflow) if self.position is None else self.position
        workflow.insert(index, dict(self.step))
        defn["workflow"] = _renumber(workflow)
        return _child(version, defn, self.name)


class WorkflowStepRemoveMutator(Mutator):
    """Remove the workflow step named `step_name` (no-op when absent)."""

    name = "workflow-step-remove"

    def __init__(self, step_name: str, *, name: str | None = None) -> None:
        super().__init__(name=name or f"workflow-step-remove:{step_name}")
        self.step_name = step_name

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        workflow = [dict(s) for s in (defn.get("workflow") or [])]
        kept = [s for s in workflow if s.get("name") != self.step_name]
        if len(kept) == len(workflow):
            return None
        defn["workflow"] = _renumber(kept)
        return _child(version, defn, self.name)


class ToolAttachMutator(Mutator):
    """Attach a ToolDefinition-shaped dict to the agent's extra_tools."""

    name = "tool-attach"

    def __init__(self, tool: dict[str, Any], *, name: str | None = None) -> None:
        tool_name = (tool.get("header") or {}).get("name")
        super().__init__(name=name or f"tool-attach:{tool_name}")
        self.tool = dict(tool)
        self.tool_name = tool_name

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        tools = [dict(t) for t in (defn.get("extra_tools") or [])]
        if any((t.get("header") or {}).get("name") == self.tool_name
               for t in tools):
            return None
        tools.append(dict(self.tool))
        defn["extra_tools"] = tools
        return _child(version, defn, self.name)


class ToolDetachMutator(Mutator):
    """Remove the tool named `tool_name` from extra_tools (no-op if absent)."""

    name = "tool-detach"

    def __init__(self, tool_name: str, *, name: str | None = None) -> None:
        super().__init__(name=name or f"tool-detach:{tool_name}")
        self.tool_name = tool_name

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        tools = [dict(t) for t in (defn.get("extra_tools") or [])]
        kept = [t for t in tools
                if (t.get("header") or {}).get("name") != self.tool_name]
        if len(kept) == len(tools):
            return None
        defn["extra_tools"] = kept
        return _child(version, defn, self.name)


_WORKFLOW_EDIT_GUIDANCE = (
    "You are editing an agent's WORKFLOW (a JSON array of steps with"
    " name + instructions, optionally subagents). context.failures and"
    " context.teacher/student evidence show where the current workflow"
    " falls short. Return ONLY the full edited JSON array: you may add"
    " steps (e.g. an extra verification pass), remove steps that add no"
    " value, reorder, or rewrite instructions. Keep existing 'subagents'"
    " references intact unless removing the step. No prose outside the"
    " JSON."
)


class LLMWorkflowEditor(Mutator):
    """Ask the LLM to restructure the workflow itself.

    The LLM receives the current workflow as JSON (plus failure/gap
    evidence from the context) and returns a full edited array. The
    result is validated — parseable JSON, a non-empty list, every step
    carrying a name — and renumbered; anything else is rejected (None),
    so a malformed proposal can never enter the loop.
    """

    name = "llm-workflow-editor"

    def __init__(
        self, *, gap_source: Any = None,
        model: str | None = None, name: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self.gap_source = gap_source
        self.model = model

    def _gap(self) -> dict[str, Any]:
        if self.gap_source is None:
            return {}
        if callable(self.gap_source):
            return dict(self.gap_source() or {})
        return dict(self.gap_source)

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent" or ctx.llm is None:
            return None
        defn = dict(version.definition)
        workflow = defn.get("workflow") or []
        if not workflow:
            return None
        gap = self._gap()
        try:
            response = ctx.llm.rewrite(
                target=json.dumps(workflow, indent=2, default=str),
                guidance=_WORKFLOW_EDIT_GUIDANCE,
                context={
                    "failures": ctx.failures,
                    "teacher_excerpt": gap.get("teacher_excerpt", ""),
                    "student_excerpt": gap.get("student_excerpt", ""),
                    "system_prompt": defn.get("system_prompt", ""),
                },
                model=self.model,
            )
        except Exception:  # a flaky editor must not sink the round
            return None
        edited = _parse_workflow(response)
        if edited is None:
            return None
        renumbered = _renumber(edited)
        if renumbered == _renumber([dict(s) for s in workflow]):
            return None
        defn["workflow"] = renumbered
        return _child(version, defn, self.name)


def _parse_workflow(text: str) -> list[dict[str, Any]] | None:
    """Extract + validate a workflow JSON array from LLM output."""
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(
            line for line in lines if not line.startswith("```")
        )
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(candidate[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    steps: list[dict[str, Any]] = []
    for entry in parsed:
        if not isinstance(entry, dict) or not entry.get("name"):
            return None
        steps.append(dict(entry))
    return steps
