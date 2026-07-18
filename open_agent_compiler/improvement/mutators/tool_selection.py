"""Tool-selection / tool-sequence mutators — optimise tool USAGE, not prose.

The Phase-13 mutators (`ToolDescriptionAppendMutator`, `ToolRuleAddMutator`,
`ToolFormatMutator`) tune how individual tools are *described* and *formatted*.
This module adds the missing axis the Phase-E "deep tool-use" mandate needs:
mutate WHICH tools the agent uses and in WHAT order — so the loop can optimise
the agent's tool USAGE for a client's use case, not just the wording around it.

Two agent-kind mutators, both pure (no LLM, no randomness):

  * `ToolSelectionMutator` — enable or disable one named tool on the agent's
    enabled-tool surface. "Disable" prunes the tool from the agent's
    `extra_tools` list AND from every workflow step's `tool_uses` (so a tool
    the loop finds counter-productive for this client stops being offered).
    "Enable" re-adds a known tool name to the agent's `enabled_tools` allow-list
    (used when the agent definition carries an explicit allow-list the compiler
    emits — e.g. the merged per-client capability allow-list). Idempotent: a
    no-op change returns None so the loop never churns on it.

  * `ToolSequenceMutator` — reorder the agent's multi-step `workflow` so a
    given tool's step runs earlier/later, OR reorder the `tool_uses` inside one
    step. Reshaping the sequence is how the loop discovers a better order of
    operations for the client's task (e.g. "search the client's Drive BEFORE
    drafting" vs after). Renumbers `WorkflowStepDefinition.id` after a reorder
    so the compiled STEP-N labels stay 1..N and contiguous.

Both operate on the agent's `definition` dict (a model_dump of AgentDefinition),
so they slot into the same `IterativeLoop` as every other mutator and emit
lineage-linked `ComponentVersion`s via `ComponentVersion.of`.
"""

from __future__ import annotations

from typing import Any, Literal

from open_agent_compiler.improvement.mutators.base import Mutator, MutationContext
from open_agent_compiler.improvement.version import ComponentVersion

ToolSelectionAction = Literal["enable", "disable"]


def _tool_name_of(entry: Any) -> str | None:
    """Best-effort tool name from an extra_tools entry (a ToolDefinition dump)."""
    if not isinstance(entry, dict):
        return None
    header = entry.get("header")
    if isinstance(header, dict) and isinstance(header.get("name"), str):
        return header["name"]
    # Tolerate a flat {"name": ...} shape too.
    if isinstance(entry.get("name"), str):
        return entry["name"]
    return None


class ToolSelectionMutator(Mutator):
    """Enable or disable one tool on an agent's tool surface.

    `action="disable"` removes `tool_name` from `extra_tools` and from every
    workflow step's `tool_uses`, and drops it from an `enabled_tools` allow-list
    if present. `action="enable"` adds `tool_name` to the agent's
    `enabled_tools` allow-list (creating it if absent) — the declarative
    allow-list the personalized compile emits into opencode.json. Returns None
    when the change would be a no-op (tool already in the desired state), so the
    loop doesn't register churn candidates.
    """

    name = "tool-selection"

    def __init__(
        self,
        tool_name: str,
        action: ToolSelectionAction = "disable",
        *,
        name: str | None = None,
    ) -> None:
        if action not in ("enable", "disable"):
            raise ValueError(
                f"action must be 'enable'/'disable', not {action!r}"
            )
        super().__init__(name=name or f"{self.name}:{action}:{tool_name}")
        self.tool_name = tool_name
        self.action = action

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        if self.action == "enable":
            changed = self._enable(defn)
        else:
            changed = self._disable(defn)
        if not changed:
            return None
        return ComponentVersion.of(
            component_id=version.component_id, kind=version.kind,
            definition=defn, parent_hash=version.content_hash,
            author=self.name,
        )

    def _enable(self, defn: dict[str, Any]) -> bool:
        allow = list(defn.get("enabled_tools") or [])
        if self.tool_name in allow:
            return False
        allow.append(self.tool_name)
        defn["enabled_tools"] = allow
        return True

    def _disable(self, defn: dict[str, Any]) -> bool:
        changed = False

        allow = defn.get("enabled_tools")
        if isinstance(allow, list) and self.tool_name in allow:
            defn["enabled_tools"] = [t for t in allow if t != self.tool_name]
            changed = True

        extra = defn.get("extra_tools")
        if isinstance(extra, list):
            kept = [e for e in extra if _tool_name_of(e) != self.tool_name]
            if len(kept) != len(extra):
                defn["extra_tools"] = kept
                changed = True

        workflow = defn.get("workflow")
        if isinstance(workflow, list):
            new_steps = []
            for step in workflow:
                if not isinstance(step, dict):
                    new_steps.append(step)
                    continue
                uses = step.get("tool_uses")
                if isinstance(uses, list):
                    pruned = [
                        u for u in uses
                        if not (isinstance(u, dict)
                                and u.get("tool_name") == self.tool_name)
                    ]
                    if len(pruned) != len(uses):
                        step = {**step, "tool_uses": pruned}
                        changed = True
                new_steps.append(step)
            if changed:
                defn["workflow"] = new_steps
        return changed


def _renumber(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-id workflow steps to 1..N so compiled STEP labels stay contiguous."""
    out: list[dict[str, Any]] = []
    for i, step in enumerate(steps, start=1):
        if isinstance(step, dict) and step.get("id") != i:
            out.append({**step, "id": i})
        else:
            out.append(step)
    return out


class ToolSequenceMutator(Mutator):
    """Reorder an agent's multi-step workflow or a step's tool_uses.

    Two modes:

      * mode="step" (default): move the workflow step that USES `tool_name`
        toward the front (`direction="earlier"`) or back (`direction="later"`)
        by one position. Renumbers step ids after the move. This reshapes the
        order of operations — the core of optimising a multi-step / orchestrator
        agent's tool sequence for the client's task.
      * mode="within_step": within the FIRST step that uses `tool_name`, move
        that tool's `tool_uses` entry earlier/later by one — tuning the order
        tools are called inside a single step.

    Returns None when the move is a no-op (tool not found, already at the
    boundary, or fewer than two reorderable items).
    """

    name = "tool-sequence"

    def __init__(
        self,
        tool_name: str,
        *,
        direction: Literal["earlier", "later"] = "earlier",
        mode: Literal["step", "within_step"] = "step",
        name: str | None = None,
    ) -> None:
        if direction not in ("earlier", "later"):
            raise ValueError(
                f"direction must be 'earlier'/'later', not {direction!r}"
            )
        if mode not in ("step", "within_step"):
            raise ValueError(
                f"mode must be 'step'/'within_step', not {mode!r}"
            )
        super().__init__(
            name=name or f"{self.name}:{mode}:{direction}:{tool_name}"
        )
        self.tool_name = tool_name
        self.direction = direction
        self.mode = mode

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        workflow = defn.get("workflow")
        if not isinstance(workflow, list) or len(workflow) < 1:
            return None
        if self.mode == "step":
            new_workflow = self._move_step(workflow)
        else:
            new_workflow = self._move_within_step(workflow)
        if new_workflow is None:
            return None
        defn["workflow"] = new_workflow
        return ComponentVersion.of(
            component_id=version.component_id, kind=version.kind,
            definition=defn, parent_hash=version.content_hash,
            author=self.name,
        )

    def _step_uses_tool(self, step: Any) -> bool:
        if not isinstance(step, dict):
            return False
        uses = step.get("tool_uses")
        if not isinstance(uses, list):
            return False
        return any(
            isinstance(u, dict) and u.get("tool_name") == self.tool_name
            for u in uses
        )

    def _move_step(
        self, workflow: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        if len(workflow) < 2:
            return None
        idx = next(
            (i for i, s in enumerate(workflow) if self._step_uses_tool(s)),
            None,
        )
        if idx is None:
            return None
        target = idx - 1 if self.direction == "earlier" else idx + 1
        if target < 0 or target >= len(workflow):
            return None
        reordered = list(workflow)
        reordered[idx], reordered[target] = reordered[target], reordered[idx]
        return _renumber(reordered)

    def _move_within_step(
        self, workflow: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        for i, step in enumerate(workflow):
            if not self._step_uses_tool(step):
                continue
            uses = list(step["tool_uses"])
            if len(uses) < 2:
                return None
            pos = next(
                (j for j, u in enumerate(uses)
                 if isinstance(u, dict)
                 and u.get("tool_name") == self.tool_name),
                None,
            )
            if pos is None:
                return None
            target = pos - 1 if self.direction == "earlier" else pos + 1
            if target < 0 or target >= len(uses):
                return None
            uses[pos], uses[target] = uses[target], uses[pos]
            new_workflow = list(workflow)
            new_workflow[i] = {**step, "tool_uses": uses}
            return new_workflow
        return None


__all__ = [
    "ToolSelectionAction",
    "ToolSelectionMutator",
    "ToolSequenceMutator",
]
