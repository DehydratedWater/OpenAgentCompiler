"""Tool-selection / tool-sequence mutators (Phase E deep tool-use axis)."""

from __future__ import annotations

from open_agent_compiler.improvement.mutators import (
    MutationContext,
    ToolSelectionMutator,
    ToolSequenceMutator,
)
from open_agent_compiler.improvement.version import ComponentVersion


def _agent(**overrides) -> dict:
    base = {
        "name": "orch",
        "system_prompt": "do the work",
        "extra_tools": [
            {"header": {"name": "search_drive"}},
            {"header": {"name": "draft_reply"}},
        ],
        "enabled_tools": ["search_drive", "draft_reply"],
        "workflow": [
            {"id": 1, "name": "draft", "tool_uses": [{"tool_name": "draft_reply"}]},
            {"id": 2, "name": "lookup", "tool_uses": [{"tool_name": "search_drive"}]},
        ],
    }
    base.update(overrides)
    return base


def _v(definition: dict | None = None, kind: str = "agent") -> ComponentVersion:
    return ComponentVersion.of(
        component_id="orch", kind=kind, definition=definition or _agent(),
    )


# ---- ToolSelectionMutator ----------------------------------------------


def test_disable_prunes_from_extra_tools_workflow_and_allow_list() -> None:
    v = _v()
    out = ToolSelectionMutator("search_drive", "disable").mutate(v, MutationContext())
    assert out is not None
    names = [t["header"]["name"] for t in out.definition["extra_tools"]]
    assert "search_drive" not in names
    assert "search_drive" not in out.definition["enabled_tools"]
    # the workflow step that only used search_drive now has no tool_uses for it
    all_uses = [
        u["tool_name"]
        for step in out.definition["workflow"]
        for u in step["tool_uses"]
    ]
    assert "search_drive" not in all_uses
    assert out.parent_hash == v.content_hash


def test_disable_unknown_tool_is_noop() -> None:
    assert (
        ToolSelectionMutator("nope", "disable").mutate(_v(), MutationContext())
        is None
    )


def test_enable_adds_to_allow_list() -> None:
    defn = _agent(enabled_tools=["draft_reply"])
    out = ToolSelectionMutator("search_drive", "enable").mutate(
        _v(defn), MutationContext()
    )
    assert out is not None
    assert "search_drive" in out.definition["enabled_tools"]


def test_enable_already_present_is_noop() -> None:
    assert (
        ToolSelectionMutator("draft_reply", "enable").mutate(_v(), MutationContext())
        is None
    )


def test_enable_creates_allow_list_when_absent() -> None:
    defn = _agent()
    defn.pop("enabled_tools")
    out = ToolSelectionMutator("new_tool", "enable").mutate(_v(defn), MutationContext())
    assert out is not None
    assert out.definition["enabled_tools"] == ["new_tool"]


def test_selection_skips_non_agent() -> None:
    v = ComponentVersion.of("t", "tool", {"description": "x"})
    assert ToolSelectionMutator("x", "disable").mutate(v, MutationContext()) is None


# ---- ToolSequenceMutator (step reorder) --------------------------------


def test_move_step_earlier_swaps_and_renumbers() -> None:
    # search_drive is the 2nd step; move it earlier → it becomes step 1.
    v = _v()
    out = ToolSequenceMutator("search_drive", direction="earlier").mutate(
        v, MutationContext()
    )
    assert out is not None
    wf = out.definition["workflow"]
    assert wf[0]["name"] == "lookup"  # search step moved to front
    assert wf[1]["name"] == "draft"
    # ids renumbered 1..N contiguous
    assert [s["id"] for s in wf] == [1, 2]


def test_move_step_at_boundary_is_noop() -> None:
    # draft_reply is already the first step; can't move earlier.
    assert (
        ToolSequenceMutator("draft_reply", direction="earlier").mutate(
            _v(), MutationContext()
        )
        is None
    )


def test_move_step_later() -> None:
    out = ToolSequenceMutator("draft_reply", direction="later").mutate(
        _v(), MutationContext()
    )
    assert out is not None
    wf = out.definition["workflow"]
    assert wf[0]["name"] == "lookup"
    assert wf[1]["name"] == "draft"


def test_move_step_unknown_tool_is_noop() -> None:
    assert (
        ToolSequenceMutator("nope").mutate(_v(), MutationContext()) is None
    )


def test_single_step_workflow_cannot_reorder_steps() -> None:
    defn = _agent(
        workflow=[{"id": 1, "name": "only", "tool_uses": [{"tool_name": "search_drive"}]}]
    )
    assert ToolSequenceMutator("search_drive").mutate(_v(defn), MutationContext()) is None


# ---- ToolSequenceMutator (within-step reorder) -------------------------


def test_move_within_step_reorders_tool_uses() -> None:
    defn = _agent(
        workflow=[
            {
                "id": 1,
                "name": "combo",
                "tool_uses": [
                    {"tool_name": "draft_reply"},
                    {"tool_name": "search_drive"},
                ],
            }
        ]
    )
    out = ToolSequenceMutator(
        "search_drive", direction="earlier", mode="within_step"
    ).mutate(_v(defn), MutationContext())
    assert out is not None
    uses = [u["tool_name"] for u in out.definition["workflow"][0]["tool_uses"]]
    assert uses == ["search_drive", "draft_reply"]


def test_within_step_single_use_is_noop() -> None:
    out = ToolSequenceMutator(
        "search_drive", mode="within_step"
    ).mutate(_v(), MutationContext())
    assert out is None
