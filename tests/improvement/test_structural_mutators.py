"""Structural mutators — workflow steps and tool surface as loop targets."""

from __future__ import annotations

from open_agent_compiler.improvement import (
    LLMWorkflowEditor,
    ToolAttachMutator,
    ToolDetachMutator,
    WorkflowStepAppendMutator,
    WorkflowStepRemoveMutator,
)
from open_agent_compiler.improvement.mutators import MutationContext
from open_agent_compiler.improvement.mutators.llm import _StubLLM
from open_agent_compiler.improvement.version import ComponentVersion


def _agent(**extra) -> ComponentVersion:
    return ComponentVersion.of(
        component_id="impl", kind="agent",
        definition={
            "system_prompt": "do things",
            "workflow": [
                {"id": 1, "name": "Plan", "instructions": "plan it"},
                {"id": 2, "name": "Implement", "instructions": "do it"},
            ],
            **extra,
        },
    )


def _ctx(llm=None) -> MutationContext:
    return MutationContext(llm=llm)


# ---- workflow step append/remove ---------------------------------------


def test_append_step_at_end_and_renumber() -> None:
    child = WorkflowStepAppendMutator(
        {"name": "Verify", "instructions": "run tests"},
    ).mutate(_agent(), _ctx())
    names = [s["name"] for s in child.definition["workflow"]]
    assert names == ["Plan", "Implement", "Verify"]
    assert [s["id"] for s in child.definition["workflow"]] == [1, 2, 3]


def test_append_step_at_position() -> None:
    child = WorkflowStepAppendMutator(
        {"name": "Research", "instructions": "read first"}, position=0,
    ).mutate(_agent(), _ctx())
    assert child.definition["workflow"][0]["name"] == "Research"
    assert child.definition["workflow"][0]["id"] == 1


def test_append_is_idempotent_on_existing_name() -> None:
    mutator = WorkflowStepAppendMutator({"name": "Implement"})
    assert mutator.mutate(_agent(), _ctx()) is None


def test_remove_step_and_renumber() -> None:
    child = WorkflowStepRemoveMutator("Plan").mutate(_agent(), _ctx())
    assert [s["name"] for s in child.definition["workflow"]] == ["Implement"]
    assert child.definition["workflow"][0]["id"] == 1
    assert WorkflowStepRemoveMutator("Missing").mutate(_agent(), _ctx()) is None


def test_children_carry_lineage() -> None:
    parent = _agent()
    child = WorkflowStepAppendMutator({"name": "V"}).mutate(parent, _ctx())
    assert child.parent_hash == parent.content_hash
    assert child.author.startswith("workflow-step-append")


# ---- tool attach/detach ------------------------------------------------

_TOOL = {"header": {"name": "notes-db", "description": "d",
                    "usage_explanation_long": "l",
                    "usage_explanation_short": "s", "rules": []}}


def test_attach_and_detach_tool() -> None:
    attached = ToolAttachMutator(_TOOL).mutate(_agent(), _ctx())
    tools = attached.definition["extra_tools"]
    assert [t["header"]["name"] for t in tools] == ["notes-db"]
    # Attaching again on the child no-ops.
    assert ToolAttachMutator(_TOOL).mutate(attached, _ctx()) is None
    detached = ToolDetachMutator("notes-db").mutate(attached, _ctx())
    assert detached.definition["extra_tools"] == []
    assert ToolDetachMutator("notes-db").mutate(_agent(), _ctx()) is None


# ---- LLM workflow editor -----------------------------------------------


def test_llm_workflow_editor_applies_valid_edit() -> None:
    llm = _StubLLM(response=(
        '[{"name": "Plan", "instructions": "plan it"},'
        ' {"name": "Implement", "instructions": "do it"},'
        ' {"name": "Verify", "instructions": "run the tests"}]'
    ))
    child = LLMWorkflowEditor().mutate(_agent(), _ctx(llm))
    assert [s["name"] for s in child.definition["workflow"]] == [
        "Plan", "Implement", "Verify"]
    assert [s["id"] for s in child.definition["workflow"]] == [1, 2, 3]
    # The current workflow was handed to the LLM as the rewrite target.
    assert "Implement" in llm.calls[0]["target"]


def test_llm_workflow_editor_rejects_garbage() -> None:
    for bad in ("not json", "[]", '[{"instructions": "no name"}]', '{"a": 1}'):
        assert LLMWorkflowEditor().mutate(_agent(), _ctx(_StubLLM(bad))) is None


def test_llm_workflow_editor_nops_on_no_change() -> None:
    llm = _StubLLM(response=(
        '[{"name": "Plan", "instructions": "plan it"},'
        ' {"name": "Implement", "instructions": "do it"}]'
    ))
    assert LLMWorkflowEditor().mutate(_agent(), _ctx(llm)) is None


def test_llm_workflow_editor_forwards_gap_evidence() -> None:
    llm = _StubLLM(response='[{"name": "New", "instructions": "x"}]')
    gaps = {"teacher_excerpt": "teacher did X", "student_excerpt": "student didn't"}
    LLMWorkflowEditor(gap_source=lambda: gaps).mutate(_agent(), _ctx(llm))
    assert llm.calls[0]["context"]["teacher_excerpt"] == "teacher did X"


def test_llm_workflow_editor_strips_code_fences() -> None:
    llm = _StubLLM(response=(
        "```json\n"
        '[{"name": "Only", "instructions": "x"}]\n'
        "```"
    ))
    child = LLMWorkflowEditor().mutate(_agent(), _ctx(llm))
    assert [s["name"] for s in child.definition["workflow"]] == ["Only"]
