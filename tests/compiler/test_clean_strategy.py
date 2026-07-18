"""Multi-variant clean strategy + postfix-collision validation."""

from __future__ import annotations

from pathlib import Path

import pytest

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
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.model.core.variant_spec import VariantSpec


def _factory():
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


def _preset(name: str = "p", model_id: str = "m") -> ModelPreset:
    return ModelPreset(
        name=name, provider="x", model_id=model_id,
        sampling=SamplingDefaults(temperature=0.0),
    )


def test_two_variants_with_same_postfix_rejected_at_construction(tmp_target: Path) -> None:
    with pytest.raises(ValueError, match="share postfix"):
        CompileScript(
            target=tmp_target, factory=_factory, config="c",
            variants=[
                VariantSpec(name="a", postfix="-x", preset=_preset()),
                VariantSpec(name="b", postfix="-x", preset=_preset()),
            ],
        )


def test_full_clean_removes_everything_before_first_variant(tmp_target: Path) -> None:
    stale = tmp_target / "stale.md"
    stale.write_text("leftover")
    CompileScript(
        target=tmp_target, factory=_factory, config="c", clean=True,
        variants=[
            VariantSpec(name="a", postfix="-a", preset=_preset()),
            VariantSpec(name="b", postfix="-b", preset=_preset()),
        ],
    ).run()
    assert not stale.exists()
    assert (tmp_target / ".opencode" / "agents" / "primary-a.md").exists()
    assert (tmp_target / ".opencode" / "agents" / "primary-b.md").exists()


def test_per_variant_clean_only_touches_matching_postfix(tmp_target: Path) -> None:
    # Pre-populate one stale file per variant in the layout the compiler writes.
    agents_dir = tmp_target / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    stale_a = agents_dir / "primary-a.md"
    stale_b = agents_dir / "primary-b.md"
    untouched = tmp_target / "untouched.txt"
    stale_a.write_text("old-a")
    stale_b.write_text("old-b")
    untouched.write_text("keep me")

    CompileScript(
        target=tmp_target, factory=_factory, config="c",
        clean_strategy="per_variant",
        variants=[
            VariantSpec(name="a", postfix="-a", preset=_preset()),
        ],
    ).run()

    # The -a stale was removed and re-written; -b stays untouched.
    assert (tmp_target / ".opencode" / "agents" / "primary-a.md").read_text() != "old-a"
    assert stale_b.read_text() == "old-b"
    assert untouched.read_text() == "keep me"


def test_clean_strategy_overrides_clean_bool(tmp_target: Path) -> None:
    leftover = tmp_target / "leftover.md"
    leftover.write_text("x")
    CompileScript(
        target=tmp_target, factory=_factory, config="c",
        clean=True, clean_strategy="none",
        variants=[VariantSpec(name="a", postfix="-a", preset=_preset())],
    ).run()
    assert leftover.exists()


def test_effective_clean_strategy_defaults(tmp_target: Path) -> None:
    none_script = CompileScript(
        target=tmp_target, factory=_factory, config="c",
    )
    full_script = CompileScript(
        target=tmp_target, factory=_factory, config="c", clean=True,
    )
    assert none_script.effective_clean_strategy() == "none"
    assert full_script.effective_clean_strategy() == "full"
