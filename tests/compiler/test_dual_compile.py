"""TemplateSlot.also_compile_as_primary → dual-emit semantics."""

from __future__ import annotations

from pathlib import Path


from open_agent_compiler.compiler.dialects.opencode.compiler import OpenCodeCompiler
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry


def _registry(also_primary: bool = False) -> AgentRegistry:
    reg = AgentRegistry()
    a = AgentDefinition(
        header=AgentHeader(
            agent_id="scorer", name="scorer", description="judge",
        ),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="you score",
    )
    aid = reg.register_agent(
        "scorer", a, ModelParameters(model_name="z/m", temperature=0.0),
    )
    reg.register_template(TemplateTree(
        name="t", slots=[
            TemplateSlot(name="primary", default_agent_id=aid),
            TemplateSlot(
                name="scorer", default_agent_id=aid,
                also_compile_as_primary=also_primary,
            ),
        ],
    ))
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="t"))
    return reg


def test_default_slot_emits_only_one_file(tmp_path: Path) -> None:
    """Without the flag, slot only produces its own mode-derived file."""
    reg = _registry(also_primary=False)
    OpenCodeCompiler(
        target=tmp_path, resolved_variants=reg.resolve_config("prod"),
    ).compile()
    files = sorted((tmp_path / ".opencode" / "agents").iterdir())
    names = {p.stem for p in files}
    assert names == {"primary", "scorer"}


def test_slot_with_flag_emits_both_subagent_and_primary(tmp_path: Path) -> None:
    """`also_compile_as_primary=True` produces <name>.md + <name>-primary.md."""
    reg = _registry(also_primary=True)
    OpenCodeCompiler(
        target=tmp_path, resolved_variants=reg.resolve_config("prod"),
    ).compile()
    files = sorted((tmp_path / ".opencode" / "agents").iterdir())
    names = {p.stem for p in files}
    assert names == {"primary", "scorer", "scorer-primary"}

    # The subagent file stays subagent-mode; the -primary file is primary-mode.
    sub = (tmp_path / ".opencode" / "agents" / "scorer.md").read_text()
    pri = (tmp_path / ".opencode" / "agents" / "scorer-primary.md").read_text()
    assert "mode: subagent" in sub
    assert "mode: primary" in pri


def test_dual_compile_skipped_for_primary_slot(tmp_path: Path) -> None:
    """A slot already named 'primary' shouldn't duplicate itself."""
    reg = AgentRegistry()
    a = AgentDefinition(
        header=AgentHeader(agent_id="p", name="p", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="be helpful",
    )
    aid = reg.register_agent(
        "p", a, ModelParameters(model_name="z/m", temperature=0.0),
    )
    reg.register_template(TemplateTree(
        name="t", slots=[
            TemplateSlot(
                name="primary", default_agent_id=aid,
                also_compile_as_primary=True,  # redundant on a primary slot
            ),
        ],
    ))
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="t"))
    OpenCodeCompiler(
        target=tmp_path, resolved_variants=reg.resolve_config("prod"),
    ).compile()
    files = sorted((tmp_path / ".opencode" / "agents").iterdir())
    names = {p.stem for p in files}
    # No "primary-primary" — the flag is a no-op when the slot is already
    # primary.
    assert names == {"primary"}


def test_dual_compile_preserves_subagent_permission_block(tmp_path: Path) -> None:
    """The two files share permissions but diverge on `mode:` only."""
    reg = _registry(also_primary=True)
    OpenCodeCompiler(
        target=tmp_path, resolved_variants=reg.resolve_config("prod"),
    ).compile()
    sub = (tmp_path / ".opencode" / "agents" / "scorer.md").read_text()
    pri = (tmp_path / ".opencode" / "agents" / "scorer-primary.md").read_text()
    # Same permissions framework (default deny-all)
    assert "'*': deny" in sub
    assert "'*': deny" in pri
    # System prompt content identical
    assert "you score" in sub
    assert "you score" in pri
