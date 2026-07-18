"""End-to-end: multi-variant compile writes side-by-side files."""

from __future__ import annotations

from pathlib import Path

import yaml

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
    agent = AgentDefinition(
        header=AgentHeader(agent_id="x", name="orch", description="orch"),
        usage_explanation_long="l", usage_explanation_short="s",
    )
    agent_id = reg.register_agent(
        "orch", agent, ModelParameters(model_name="base", temperature=0.0)
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
    return reg


def _preset(name: str, model_id: str, temp: float = 0.0) -> ModelPreset:
    return ModelPreset(
        name=name,
        provider="zai-coding-plan",
        model_id=model_id,
        sampling=SamplingDefaults(temperature=temp),
    )


def _frontmatter(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---")[1])


def test_three_variants_produce_three_files(tmp_target: Path) -> None:
    specs = [
        VariantSpec(name="default", postfix="", preset=_preset("default", "glm-4.5-air")),
        VariantSpec(name="glm47", postfix="-glm47", preset=_preset("glm47", "glm-4.7")),
        VariantSpec(name="qwen", postfix="-qwen35", preset=_preset("qwen", "qwen35-27b")),
    ]
    script = CompileScript(
        target=tmp_target, factory=_factory, config="prod", variants=specs
    )
    result = script.run()
    files = {p.name for p in result.written_files}
    assert "primary.md" in files
    assert "primary-glm47.md" in files
    assert "primary-qwen35.md" in files
    assert result.variants == ["default", "glm47", "qwen"]


def test_each_variant_emits_its_preset_model_in_frontmatter(tmp_target: Path) -> None:
    specs = [
        VariantSpec(name="default", postfix="", preset=_preset("default", "glm-4.5-air")),
        VariantSpec(name="glm47", postfix="-glm47", preset=_preset("glm47", "glm-4.7", 0.3)),
    ]
    CompileScript(
        target=tmp_target, factory=_factory, config="prod", variants=specs
    ).run()
    default_fm = _frontmatter(tmp_target / ".opencode" / "agents" / "primary.md")
    glm47_fm = _frontmatter(tmp_target / ".opencode" / "agents" / "primary-glm47.md")
    assert default_fm["model"] == "zai-coding-plan/glm-4.5-air"
    assert glm47_fm["model"] == "zai-coding-plan/glm-4.7"


def test_dry_run_with_variants_does_not_write(tmp_target: Path) -> None:
    specs = [
        VariantSpec(name="default", preset=_preset("default", "glm-4.5-air")),
        VariantSpec(name="glm47", postfix="-glm47", preset=_preset("glm47", "glm-4.7")),
    ]
    result = CompileScript(
        target=tmp_target, factory=_factory, config="prod",
        variants=specs, dry_run=True,
    ).run()
    assert result.dry_run is True
    assert result.variants == ["default", "glm47"]
    assert not any(tmp_target.rglob("*.md"))
