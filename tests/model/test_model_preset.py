"""ModelPreset + registry.register_agent_with_preset()."""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.model_preset import (
    ModelLimits,
    ModelPreset,
    SamplingDefaults,
)


def _agent() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(agent_id="x", name="x", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
    )


def _preset(name: str, model_id: str = "claude-sonnet-4-5") -> ModelPreset:
    return ModelPreset(
        name=name,
        provider="anthropic",
        model_id=model_id,
        sampling=SamplingDefaults(temperature=0.0, top_p=0.95),
        limits=ModelLimits(context=200_000, output=32_768),
        reasoning=True,
        interleaved=True,
    )


def test_preset_projects_to_legacy_model_parameters() -> None:
    p = _preset("fast")
    mp = p.to_model_parameters()
    assert mp.model_name == "anthropic/claude-sonnet-4-5"
    assert mp.temperature == 0.0


def test_register_with_preset_yields_distinct_id() -> None:
    reg = AgentRegistry()
    agent_id = reg.register_agent_with_preset("joke", _agent(), _preset("fast"))
    # Discriminator uses preset name, not model id.
    assert agent_id == "joke_fast_t0.0"


def test_two_presets_same_model_id_differ_by_preset_name() -> None:
    reg = AgentRegistry()
    a = reg.register_agent_with_preset(
        "joke", _agent(), _preset("fast", model_id="claude-sonnet-4-5"),
    )
    b = reg.register_agent_with_preset(
        "joke", _agent(), _preset("deep", model_id="claude-sonnet-4-5"),
    )
    assert a != b
    assert a == "joke_fast_t0.0"
    assert b == "joke_deep_t0.0"


def test_preset_round_trip_recoverable_from_registry() -> None:
    reg = AgentRegistry()
    preset = _preset("fast")
    agent_id = reg.register_agent_with_preset("joke", _agent(), preset)
    assert reg.preset_for(agent_id) == preset
    assert reg.list_presets() == ["fast"]
    assert reg.get_preset("fast") == preset


def test_registering_same_preset_name_twice_with_different_config_raises() -> None:
    reg = AgentRegistry()
    reg.register_agent_with_preset("joke", _agent(), _preset("fast"))
    different = _preset("fast", model_id="some-other-model")
    with pytest.raises(ValueError, match="already registered with different config"):
        reg.register_agent_with_preset("joke2", _agent(), different)


def test_legacy_register_agent_still_returns_no_preset() -> None:
    from open_agent_compiler.model.core.agent_model import ModelParameters

    reg = AgentRegistry()
    agent_id = reg.register_agent(
        "joke", _agent(), ModelParameters(model_name="m", temperature=0.0)
    )
    assert reg.preset_for(agent_id) is None


def test_preset_and_legacy_can_coexist_for_same_name() -> None:
    from open_agent_compiler.model.core.agent_model import ModelParameters

    reg = AgentRegistry()
    legacy = reg.register_agent(
        "joke", _agent(), ModelParameters(model_name="legacy", temperature=0.0)
    )
    preset = reg.register_agent_with_preset("joke", _agent(), _preset("fast"))
    assert legacy != preset
