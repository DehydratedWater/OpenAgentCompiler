"""build_improvement_agent_definition + ImprovementAgentMutator."""

from __future__ import annotations

import json


from open_agent_compiler.improvement.criteria import Criterion, OptimisationCriterion
from open_agent_compiler.improvement.improvement_agent import (
    ImprovementAgentMutator,
    _coerce_patch_to_definition,
    build_improvement_agent_definition,
)
from open_agent_compiler.improvement.mutators import MutationContext
from open_agent_compiler.improvement.version import ComponentVersion


def _criterion() -> OptimisationCriterion:
    return OptimisationCriterion(
        name="passes", criteria=(Criterion(kind="pass_rate", target=1.0),),
    )


# ---- build_improvement_agent_definition ---------------------------------


def test_factory_returns_valid_agent_definition() -> None:
    agent = build_improvement_agent_definition(
        target="orch", criterion=_criterion(),
    )
    assert agent.header.name == "oac/improvement-agent"
    assert "orch" in agent.system_prompt
    assert agent.workflow
    assert [s.name for s in agent.workflow] == [
        "ReadArtifacts", "ClassifyFailures", "ProposeMutation",
    ]


def test_factory_preserves_criterion_metadata_in_prompt() -> None:
    crit = OptimisationCriterion(
        name="my-crit", aggregation="weighted",
        criteria=(Criterion(kind="pass_rate", target=1.0, weight=2.0),),
    )
    agent = build_improvement_agent_definition(target="orch", criterion=crit)
    assert "my-crit" in agent.system_prompt
    assert "weighted" in agent.system_prompt


def test_factory_uses_lazy_todo_mode() -> None:
    agent = build_improvement_agent_definition(
        target="orch", criterion=_criterion(),
    )
    assert agent.todo_mode == "lazy"


def test_factory_uses_custom_name() -> None:
    agent = build_improvement_agent_definition(
        target="orch", criterion=_criterion(), name="my-improver",
    )
    assert agent.header.name == "my-improver"


# ---- _coerce_patch_to_definition --------------------------------------


def test_coerce_system_prompt_patch() -> None:
    out = _coerce_patch_to_definition(
        {"name": "a", "system_prompt": "old"},
        "system_prompt", {"new_value": "new"},
    )
    assert out == {"name": "a", "system_prompt": "new"}


def test_coerce_system_prompt_empty_rejected() -> None:
    assert _coerce_patch_to_definition(
        {"name": "a"}, "system_prompt", {"new_value": ""},
    ) is None
    assert _coerce_patch_to_definition(
        {"name": "a"}, "system_prompt", {"new_value": None},
    ) is None


def test_coerce_temperature_patch_top_level() -> None:
    out = _coerce_patch_to_definition(
        {"name": "a", "temperature": 0.5},
        "temperature", {"new_value": 0.8},
    )
    assert out["temperature"] == 0.8


def test_coerce_temperature_patch_nested() -> None:
    out = _coerce_patch_to_definition(
        {"name": "a", "model_parameters": {"temperature": 0.5}},
        "temperature", {"new_value": 0.2},
    )
    assert out["model_parameters"]["temperature"] == 0.2


def test_coerce_temperature_returns_none_when_field_absent() -> None:
    assert _coerce_patch_to_definition(
        {"name": "a"}, "temperature", {"new_value": 0.5},
    ) is None


def test_coerce_tool_description_returns_none() -> None:
    # Tool description mutations target a different component; the
    # agent-level loop must skip cleanly.
    assert _coerce_patch_to_definition(
        {"name": "a"}, "tool_description",
        {"tool_name": "t", "new_value": "new"},
    ) is None


def test_coerce_subagent_inject_adds_new_entry() -> None:
    out = _coerce_patch_to_definition(
        {"name": "a", "subagents": [{"name": "existing"}]},
        "subagent_inject", {"subagent_name": "new-sa", "reason": "needed"},
    )
    assert {"name": "new-sa", "description": "needed"} in out["subagents"]


def test_coerce_subagent_inject_skips_when_already_present() -> None:
    assert _coerce_patch_to_definition(
        {"name": "a", "subagents": [{"name": "existing"}]},
        "subagent_inject", {"subagent_name": "existing"},
    ) is None


# ---- ImprovementAgentMutator ------------------------------------------


def _v(definition: dict | None = None) -> ComponentVersion:
    return ComponentVersion.of(
        component_id="orch", kind="agent",
        definition=definition or {"name": "orch", "system_prompt": "old"},
    )


def test_mutator_skips_non_agent_kinds() -> None:
    v = ComponentVersion.of("t", "tool", {"name": "t"})
    out = ImprovementAgentMutator(invoker=lambda p: "{}").mutate(v, MutationContext())
    assert out is None


def test_mutator_handles_invoker_returning_invalid_json() -> None:
    v = _v()
    out = ImprovementAgentMutator(invoker=lambda p: "not json").mutate(v, MutationContext())
    assert out is None


def test_mutator_handles_invoker_raising() -> None:
    def boom(prompt):
        raise RuntimeError("network down")

    v = _v()
    out = ImprovementAgentMutator(invoker=boom).mutate(v, MutationContext())
    assert out is None


def test_mutator_produces_candidate_on_valid_response() -> None:
    response = json.dumps({
        "mutation_kind": "system_prompt",
        "rationale": "improves clarity",
        "patch": {"new_value": "BETTER"},
    })
    v = _v()
    out = ImprovementAgentMutator(invoker=lambda p: response).mutate(v, MutationContext())
    assert out is not None
    assert out.definition["system_prompt"] == "BETTER"
    assert out.parent_hash == v.content_hash
    assert out.author == "improvement-agent:system_prompt"
    assert out.notes == "improves clarity"


def test_mutator_passes_failures_into_prompt() -> None:
    captured = {}

    def invoker(prompt):
        captured["prompt"] = prompt
        return json.dumps({
            "mutation_kind": "system_prompt", "patch": {"new_value": "x"},
        })

    failures = [{"test": "name", "evidence": "bad"}]
    ImprovementAgentMutator(invoker=invoker).mutate(
        _v(), MutationContext(failures=failures),
    )
    assert "bad" in captured["prompt"]
    assert "name" in captured["prompt"]


def test_mutator_skips_when_patch_kind_unknown() -> None:
    response = json.dumps({
        "mutation_kind": "made_up_kind", "patch": {"x": 1},
    })
    out = ImprovementAgentMutator(invoker=lambda p: response).mutate(
        _v(), MutationContext(),
    )
    assert out is None


def test_mutator_skips_when_response_missing_required_fields() -> None:
    # Missing patch
    assert ImprovementAgentMutator(invoker=lambda p: json.dumps(
        {"mutation_kind": "system_prompt"},
    )).mutate(_v(), MutationContext()) is None
    # Missing mutation_kind
    assert ImprovementAgentMutator(invoker=lambda p: json.dumps(
        {"patch": {"new_value": "x"}},
    )).mutate(_v(), MutationContext()) is None
