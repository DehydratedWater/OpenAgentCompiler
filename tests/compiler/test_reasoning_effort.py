"""reasoning_effort flows: preset → ModelParameters → pi thinking / codex TOML."""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

from open_agent_compiler.compiler.compile import build
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


def _registry(effort: str | None) -> AgentRegistry:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="thinker", description="d"),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="think hard",
    )
    aid = reg.register_agent(
        "thinker", agent,
        ModelParameters(model_name="m", reasoning_effort=effort),
    )
    reg.register_template(TemplateTree(
        name="t", slots=[TemplateSlot(name="primary", default_agent_id=aid)]))
    reg.create_compilation_config(CompilationConfig(name="c", template_name="t"))
    return reg


def test_preset_projects_reasoning_effort() -> None:
    plain = ModelPreset(name="p", provider="x", model_id="m",
                        sampling=SamplingDefaults())
    assert plain.to_model_parameters().reasoning_effort is None

    reasoning = ModelPreset(name="p", provider="x", model_id="m",
                            sampling=SamplingDefaults(), reasoning=True)
    assert reasoning.to_model_parameters().reasoning_effort == "high"

    explicit = ModelPreset(
        name="p", provider="x", model_id="m", sampling=SamplingDefaults(),
        reasoning=True, provider_options={"reasoning_effort": "xhigh"},
    )
    assert explicit.to_model_parameters().reasoning_effort == "xhigh"


def test_pi_emits_thinking_frontmatter(tmp_target: Path) -> None:
    build(tmp_target, _registry("high"), "c", dialect="pi")
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    frontmatter = yaml.safe_load(content.split("---")[1])
    assert frontmatter["thinking"] == "high"


def test_pi_omits_thinking_when_unset(tmp_target: Path) -> None:
    build(tmp_target, _registry(None), "c", dialect="pi")
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    frontmatter = yaml.safe_load(content.split("---")[1])
    assert "thinking" not in frontmatter


def test_codex_emits_model_reasoning_effort(tmp_target: Path) -> None:
    build(tmp_target, _registry("medium"), "c", dialect="codex")
    data = tomllib.loads(
        (tmp_target / ".codex" / "agents" / "primary.toml").read_text())
    assert data["model_reasoning_effort"] == "medium"


def test_codex_omits_effort_when_unset(tmp_target: Path) -> None:
    build(tmp_target, _registry(None), "c", dialect="codex")
    data = tomllib.loads(
        (tmp_target / ".codex" / "agents" / "primary.toml").read_text())
    assert "model_reasoning_effort" not in data
