"""VariantSpec + apply_variant: per-pass preset/postfix application."""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    ModelParameters,
)
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.model.core.variant_spec import VariantSpec, apply_variant


def _variant(model_name: str = "base", temp: float = 0.0) -> AgentVariant:
    return AgentVariant(
        postfix="",
        agent_mode="primary",
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="x", name="x", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
        ),
        model_parameters=ModelParameters(model_name=model_name, temperature=temp),
    )


def _preset(name: str, model_id: str = "test-model", temp: float = 0.7) -> ModelPreset:
    return ModelPreset(
        name=name,
        provider="anthropic",
        model_id=model_id,
        sampling=SamplingDefaults(temperature=temp),
    )


def test_spec_name_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        VariantSpec(name="  ", preset=_preset("p"))


def test_apply_variant_overrides_model_and_postfix() -> None:
    original = _variant()
    spec = VariantSpec(name="glm47", postfix="-glm47", preset=_preset("glm47", "glm-4.7", 0.5))
    out = apply_variant(spec, original)
    assert out.postfix == "-glm47"
    assert out.model_parameters.model_name == "anthropic/glm-4.7"
    assert out.model_parameters.temperature == 0.5
    # Original untouched
    assert original.postfix == ""
    assert original.model_parameters.model_name == "base"


def test_default_applies_to_returns_true() -> None:
    spec = VariantSpec(name="p", preset=_preset("p"))
    assert spec.applies_to(_variant()) is True


def test_default_preset_for_returns_spec_preset() -> None:
    spec = VariantSpec(name="p", preset=_preset("p", "the-model"))
    assert spec.preset_for(_variant()).model_id == "the-model"


def test_empty_postfix_is_allowed_for_default_variant() -> None:
    spec = VariantSpec(name="default", postfix="", preset=_preset("p"))
    out = apply_variant(spec, _variant())
    assert out.postfix == ""


def test_extra_providers_round_trip() -> None:
    p = _preset("p")
    vis = _preset("vision", "vision-model")
    spec = VariantSpec(name="p", preset=p, extra_providers=(vis,))
    assert spec.extra_providers == (vis,)
