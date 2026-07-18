"""SplitProfile: per-agent model_class → preset dispatch."""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    ModelParameters,
)
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.model.core.split_profile import SplitProfile
from open_agent_compiler.model.core.variant_spec import apply_variant


def _preset(name: str, model_id: str = "id", temp: float = 0.0) -> ModelPreset:
    return ModelPreset(
        name=name, provider="x", model_id=model_id,
        sampling=SamplingDefaults(temperature=temp),
    )


def _variant(model_class: str = "default") -> AgentVariant:
    return AgentVariant(
        postfix="", agent_mode="primary",
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="a", name="a", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            model_class=model_class,
        ),
        model_parameters=ModelParameters(model_name="base", temperature=0.0),
    )


def test_empty_class_map_rejected() -> None:
    fallback = _preset("p")
    with pytest.raises(ValueError, match="at least one entry"):
        SplitProfile(name="s", preset=fallback, class_map={})


def test_resolves_known_model_class() -> None:
    fast = _preset("fast", "fast-id")
    deep = _preset("deep", "deep-id")
    spec = SplitProfile(
        name="split", postfix="-split",
        preset=deep,  # fallback
        class_map={"fast": fast, "analytical": deep},
    )
    assert spec.preset_for(_variant("fast")).model_id == "fast-id"
    assert spec.preset_for(_variant("analytical")).model_id == "deep-id"


def test_unknown_class_uses_default_class() -> None:
    fast = _preset("fast", "fast-id")
    deep = _preset("deep", "deep-id")
    spec = SplitProfile(
        name="split", preset=fast,
        class_map={"fast": fast, "analytical": deep},
        default_class="analytical",
    )
    assert spec.preset_for(_variant("vision")).model_id == "deep-id"


def test_unknown_class_and_unknown_default_falls_back_to_spec_preset() -> None:
    fallback = _preset("fallback", "fallback-id")
    fast = _preset("fast", "fast-id")
    spec = SplitProfile(
        name="split", preset=fallback,
        class_map={"fast": fast},
        default_class="ghost",
    )
    assert spec.preset_for(_variant("other")).model_id == "fallback-id"


def test_vision_agents_pass_through_unchanged_by_default() -> None:
    # Parity with a mature production deployment's resolve()->None for
    # 'vision': a split profile must
    # NOT reroute a vision agent onto a text preset — it keeps its own model.
    fast = _preset("fast", "qwen-fast")
    deep = _preset("deep", "qwen-deep")
    spec = SplitProfile(
        name="qwen-split", postfix="-qwen", preset=deep,
        class_map={"fast": fast, "analytical": deep},
    )
    assert spec.applies_to(_variant("fast")) is True
    assert spec.applies_to(_variant("vision")) is False

    v_vision = apply_variant(spec, _variant("vision"))
    # untouched: original model + NO postfix applied (kept its own variant)
    assert v_vision.model_parameters.model_name == "base"
    assert v_vision.postfix == ""


def test_passthrough_classes_configurable() -> None:
    fast = _preset("fast", "fast-id")
    deep = _preset("deep", "deep-id")
    # opt nothing out → even vision gets split
    spec = SplitProfile(
        name="s", postfix="-q", preset=deep,
        class_map={"fast": fast, "analytical": deep},
        passthrough_classes=(),
    )
    assert spec.applies_to(_variant("vision")) is True
    v = apply_variant(spec, _variant("vision"))
    assert v.postfix == "-q"  # split now applied to vision too


def test_apply_variant_picks_per_agent_preset() -> None:
    fast = _preset("fast", "qwen-fast", temp=0.5)
    deep = _preset("deep", "qwen-deep", temp=0.0)
    spec = SplitProfile(
        name="qwen-split", postfix="-qwen",
        preset=deep,
        class_map={"fast": fast, "analytical": deep},
    )
    v_fast = apply_variant(spec, _variant("fast"))
    v_deep = apply_variant(spec, _variant("analytical"))
    assert v_fast.model_parameters.model_name == "x/qwen-fast"
    assert v_fast.model_parameters.temperature == 0.5
    assert v_deep.model_parameters.model_name == "x/qwen-deep"
    assert v_fast.postfix == v_deep.postfix == "-qwen"
