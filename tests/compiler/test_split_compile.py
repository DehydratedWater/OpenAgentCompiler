"""End-to-end: SplitProfile compiles one tree with mixed presets per agent."""

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
from open_agent_compiler.model.core.split_profile import SplitProfile


def _factory_with_two_classes():
    """Two slots: a 'speed-bound' fast agent and a 'reasoning' deep agent."""
    reg = AgentRegistry()
    fast_def = AgentDefinition(
        header=AgentHeader(agent_id="x", name="fast-bot", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        model_class="fast",
    )
    deep_def = AgentDefinition(
        header=AgentHeader(agent_id="x", name="deep-bot", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        model_class="analytical",
    )
    fast_id = reg.register_agent(
        "fast", fast_def, ModelParameters(model_name="base", temperature=0.0)
    )
    deep_id = reg.register_agent(
        "deep", deep_def, ModelParameters(model_name="base", temperature=0.0)
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[
                TemplateSlot(name="primary", default_agent_id=fast_id),
                TemplateSlot(name="auditor", default_agent_id=deep_id),
            ],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
    return reg


def _preset(name: str, model_id: str, temp: float = 0.0) -> ModelPreset:
    return ModelPreset(
        name=name, provider="vllm", model_id=model_id,
        sampling=SamplingDefaults(temperature=temp),
    )


def _frontmatter(p: Path) -> dict:
    return yaml.safe_load(p.read_text().split("---")[1])


def test_split_profile_compiles_mixed_preset_tree(tmp_target: Path) -> None:
    fast = _preset("fast", "qwen35-35b-a3b")
    deep = _preset("deep", "qwen35-27b-heretic")
    spec = SplitProfile(
        name="splitqwen35", postfix="-splitqwen35",
        preset=deep,
        class_map={"fast": fast, "analytical": deep},
    )
    CompileScript(
        target=tmp_target, factory=_factory_with_two_classes,
        config="prod", variants=[spec],
    ).run()

    fast_md = _frontmatter(tmp_target / ".opencode" / "agents" / "primary-splitqwen35.md")
    deep_md = _frontmatter(tmp_target / ".opencode" / "agents" / "auditor-splitqwen35.md")
    assert fast_md["model"] == "vllm/qwen35-35b-a3b"
    assert deep_md["model"] == "vllm/qwen35-27b-heretic"


def test_split_and_single_variants_in_one_pass(tmp_target: Path) -> None:
    """A SplitProfile and a plain VariantSpec mix in the same CompileScript."""
    from open_agent_compiler.model.core.variant_spec import VariantSpec

    fast = _preset("fast", "qwen35-35b-a3b")
    deep = _preset("deep", "qwen35-27b-heretic")
    glm = _preset("glm", "glm-4.5-air")

    specs = [
        VariantSpec(name="glm", postfix="-glm", preset=glm),
        SplitProfile(
            name="splitqwen35", postfix="-split",
            preset=deep, class_map={"fast": fast, "analytical": deep},
        ),
    ]
    CompileScript(
        target=tmp_target, factory=_factory_with_two_classes,
        config="prod", variants=specs,
    ).run()

    glm_primary = _frontmatter(tmp_target / ".opencode" / "agents" / "primary-glm.md")
    glm_auditor = _frontmatter(tmp_target / ".opencode" / "agents" / "auditor-glm.md")
    split_primary = _frontmatter(tmp_target / ".opencode" / "agents" / "primary-split.md")
    split_auditor = _frontmatter(tmp_target / ".opencode" / "agents" / "auditor-split.md")
    # Plain variant: both agents pin to the same model regardless of class.
    assert glm_primary["model"] == glm_auditor["model"] == "vllm/glm-4.5-air"
    # Split: fast → 35b-a3b, analytical → 27b-heretic.
    assert split_primary["model"] == "vllm/qwen35-35b-a3b"
    assert split_auditor["model"] == "vllm/qwen35-27b-heretic"
