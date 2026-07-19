"""Dialect protocol + registry + bundled dialects."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.compiler.compile import build
from open_agent_compiler.compiler.core.compiler import Compiler
from open_agent_compiler.compiler.dialects import get, list_dialects, register
from open_agent_compiler.compiler.dialects.claude_code.compiler import ClaudeCodeCompiler
from open_agent_compiler.compiler.dialects.codex.compiler import CodexCompiler
from open_agent_compiler.compiler.dialects.opencode.compiler import OpenCodeCompiler
from open_agent_compiler.compiler.dialects.pi_agent.compiler import PiAgentCompiler
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


# ---- registry contract -------------------------------------------------


def test_bundled_dialects_registered() -> None:
    names = list_dialects()
    assert "opencode" in names
    assert "claude" in names
    assert "pi" in names
    assert "codex" in names


def test_get_returns_class() -> None:
    assert get("opencode") is OpenCodeCompiler
    assert get("claude") is ClaudeCodeCompiler
    assert get("pi") is PiAgentCompiler
    assert get("codex") is CodexCompiler


def test_get_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown dialect"):
        get("does-not-exist")


def test_register_adds_custom_dialect() -> None:
    class _Stub(Compiler):
        dialect_name = "stub"
        def compile(self) -> None:
            (self.target / "stub.txt").write_text("ok")

    register("stub-test", _Stub)
    assert "stub-test" in list_dialects()
    assert get("stub-test") is _Stub


# ---- Compiler base ----------------------------------------------------


def test_compiler_base_carries_dialect_name_on_subclasses() -> None:
    assert OpenCodeCompiler.dialect_name == "opencode"
    assert ClaudeCodeCompiler.dialect_name == "claude"
    assert PiAgentCompiler.dialect_name == "pi"
    assert CodexCompiler.dialect_name == "codex"


def test_opencode_supports_expected_features() -> None:
    feats = OpenCodeCompiler.supports_features
    assert "workflow" in feats
    assert "subagents" in feats
    assert "todo_modes" in feats


def test_pi_compile_writes_pi_agents_dir(tmp_path: Path) -> None:
    """Pi compiler writes to .pi/agents/ not .opencode/agents/."""
    inst = PiAgentCompiler(tmp_path, {})
    # Empty tree should compile without error (no agents = no files)
    inst.compile()
    # The .pi/agents/ directory should exist (even if empty)
    assert (tmp_path / ".pi" / "agents").exists()


# ---- end-to-end via build() with each dialect -------------------------


def _factory():
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="x", name="orch", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="You are a helpful agent.",
    )
    agent_id = reg.register_agent(
        "orch", agent, ModelParameters(model_name="m", temperature=0.0),
    )
    reg.register_template(
        TemplateTree(
            name="t",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="c", template_name="t"))
    return reg


def test_build_with_opencode_dialect_writes_opencode_tree(tmp_target: Path) -> None:
    build(tmp_target, _factory(), "c", dialect="opencode")
    assert (tmp_target / ".opencode" / "agents" / "primary.md").exists()


def test_build_with_codex_dialect_writes_codex_tree(tmp_target: Path) -> None:
    build(tmp_target, _factory(), "c", dialect="codex")
    assert (tmp_target / ".codex" / "agents" / "primary.toml").exists()
    assert not (tmp_target / ".opencode").exists()


def test_build_with_claude_dialect_writes_claude_tree(tmp_target: Path) -> None:
    build(tmp_target, _factory(), "c", dialect="claude")
    # ClaudeCodeCompiler renames .opencode/ → .claude/ after compile.
    assert (tmp_target / ".claude" / "agents" / "primary.md").exists()
    assert not (tmp_target / ".opencode" / "agents").exists()


def test_compile_script_dialect_field_threads_through(tmp_target: Path) -> None:
    script = CompileScript(
        target=tmp_target, factory=_factory, config="c", dialect="opencode",
    )
    result = script.run()
    assert result.target == tmp_target


def test_compile_script_rejects_unknown_dialect(tmp_target: Path) -> None:
    with pytest.raises(ValueError, match="unknown dialect"):
        CompileScript(
            target=tmp_target, factory=_factory, config="c",
            dialect="bogus-dialect",
        )
