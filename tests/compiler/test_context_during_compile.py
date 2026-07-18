"""Verify the CompilationContext is active during a variant compile pass."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.compiler.script import CompileScript
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.compilation_context import current_context
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.model.core.variant_spec import VariantSpec


_OBSERVED_CONTEXTS: list[dict] = []


def _factory_observes_context():
    """Factory that records what context was active when invoked."""
    _OBSERVED_CONTEXTS.append(
        {
            "variant_name": current_context().variant_name,
            "is_local": current_context().flag("is_local", default=False),
            "access_profile": current_context().access_profile_name,
            "mock_profile": current_context().mock_profile_name,
        }
    )
    reg = AgentRegistry()
    agent_id = reg.register_agent(
        "x",
        AgentDefinition(
            header=AgentHeader(agent_id="x", name="x", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
        ),
        ModelParameters(model_name="m", temperature=0.0),
    )
    reg.register_template(
        TemplateTree(
            name="t",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="c", template_name="t"))
    return reg


def _preset(model_id: str = "m") -> ModelPreset:
    return ModelPreset(
        name="p", provider="x", model_id=model_id,
        sampling=SamplingDefaults(temperature=0.0),
    )


def test_variant_feature_flags_reach_factory(tmp_target: Path) -> None:
    _OBSERVED_CONTEXTS.clear()
    spec = VariantSpec(
        name="local-build", postfix="-local",
        preset=_preset(),
        feature_flags={"is_local": True, "extra": 42},
    )
    CompileScript(
        target=tmp_target, factory=_factory_observes_context,
        config="c", variants=[spec],
        access_profile="ci", mock_profile="happy-path",
    ).run()
    assert _OBSERVED_CONTEXTS
    ctx = _OBSERVED_CONTEXTS[-1]
    assert ctx["variant_name"] == "local-build"
    assert ctx["is_local"] is True
    assert ctx["access_profile"] == "ci"
    assert ctx["mock_profile"] == "happy-path"


def test_context_is_empty_outside_compile_pass() -> None:
    assert current_context().variant_name is None
