"""CompileScript — composable Python-side compile orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.compiler.script import CompileResult, CompileScript
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry


def _build_factory(agent: AgentDefinition, model: ModelParameters):
    def factory() -> AgentRegistry:
        reg = AgentRegistry()
        agent_id = reg.register_agent("primary", agent, model)
        reg.register_template(
            TemplateTree(
                name="tpl",
                slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
            )
        )
        reg.create_compilation_config(
            CompilationConfig(name="prod", template_name="tpl")
        )
        return reg

    return factory


def test_requires_exactly_one_factory(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
    tmp_target: Path,
) -> None:
    factory = _build_factory(minimal_agent, fast_model)
    with pytest.raises(ValueError, match="exactly one"):
        CompileScript(target=tmp_target, config="prod")
    with pytest.raises(ValueError, match="exactly one"):
        CompileScript(
            target=tmp_target,
            config="prod",
            factory=factory,
            factory_spec="x:y",
        )


def test_run_writes_files(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
    tmp_target: Path,
) -> None:
    factory = _build_factory(minimal_agent, fast_model)
    script = CompileScript(target=tmp_target, factory=factory, config="prod")
    result = script.run()
    assert isinstance(result, CompileResult)
    assert result.resolved_slots == ["primary"]
    assert result.written_files
    assert any(p.name == "primary.md" for p in result.written_files)


def test_dry_run_writes_nothing(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
    tmp_target: Path,
) -> None:
    factory = _build_factory(minimal_agent, fast_model)
    script = CompileScript(
        target=tmp_target, factory=factory, config="prod", dry_run=True
    )
    result = script.run()
    assert result.dry_run is True
    assert result.written_files == []
    assert not any(tmp_target.rglob("*.md"))


def test_clean_removes_stale_target(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
    tmp_target: Path,
) -> None:
    stale = tmp_target / "stale.txt"
    stale.write_text("leftover")
    factory = _build_factory(minimal_agent, fast_model)
    script = CompileScript(
        target=tmp_target, factory=factory, config="prod", clean=True
    )
    script.run()
    assert not stale.exists()


def test_factory_spec_string_loads_via_importlib(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
    tmp_target: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _build_factory(minimal_agent, fast_model)
    # Install factory at a known module attribute the spec can reach.
    import sys

    module_name = "tests.compiler.test_compile_script"
    monkeypatch.setattr(sys.modules[module_name], "_factory_for_spec", factory, raising=False)
    script = CompileScript(
        target=tmp_target,
        factory_spec=f"{module_name}:_factory_for_spec",
        config="prod",
    )
    result = script.run()
    assert result.resolved_slots == ["primary"]


def test_factory_spec_with_missing_colon_raises(tmp_target: Path) -> None:
    script = CompileScript(
        target=tmp_target, factory_spec="oops_no_colon", config="prod"
    )
    with pytest.raises(ValueError, match="must be 'module:callable'"):
        script.resolve_factory()
