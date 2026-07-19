"""Universal artifact loader — one introspection surface for all dialects."""

from __future__ import annotations

from pathlib import Path

import pytest

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
from open_agent_compiler.testing.artifacts import (
    list_agent_artifacts,
    load_agent_artifact,
)


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="probe", description="Probe agent."),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="You are the probe.",
    )
    aid = reg.register_agent("probe", agent, ModelParameters(model_name="m"))
    reg.register_template(TemplateTree(
        name="t", slots=[TemplateSlot(name="primary", default_agent_id=aid)]))
    reg.create_compilation_config(CompilationConfig(name="c", template_name="t"))
    return reg


@pytest.mark.parametrize("dialect", ["opencode", "claude", "pi", "codex"])
def test_load_artifact_across_all_dialects(tmp_target: Path, dialect: str) -> None:
    build(tmp_target, _registry(), "c", dialect=dialect)
    assert "primary" in list_agent_artifacts(tmp_target, dialect)
    art = load_agent_artifact(tmp_target, "primary", dialect=dialect)
    assert art.dialect == dialect
    assert art.path.exists()
    assert "You are the probe." in art.body
    # Every dialect exposes the model in its structured half.
    assert art.config.get("model") == "m"


def test_missing_artifact_raises_with_path(tmp_target: Path) -> None:
    build(tmp_target, _registry(), "c", dialect="pi")
    with pytest.raises(FileNotFoundError, match="nope"):
        load_agent_artifact(tmp_target, "nope", dialect="pi")


def test_unknown_dialect_rejected(tmp_target: Path) -> None:
    with pytest.raises(ValueError, match="unknown dialect"):
        load_agent_artifact(tmp_target, "primary", dialect="bogus")
    with pytest.raises(ValueError, match="unknown dialect"):
        list_agent_artifacts(tmp_target, "bogus")
