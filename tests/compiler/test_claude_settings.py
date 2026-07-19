"""Claude dialect: .claude/settings.json permission emission."""

from __future__ import annotations

import json
from pathlib import Path

from open_agent_compiler.compiler.compile import build
from open_agent_compiler.compiler.dialects.claude_code.compiler import _claude_bash_rule
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
    ToolPermissions,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.permissions_model import BashToolPermission
from open_agent_compiler.model.core.tools_model import (
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
)


def _bash_tool(name: str, command: str) -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name=name, description="d",
            usage_explanation_long="l", usage_explanation_short="s", rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow", allowed_commands=[command],
            ),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
        ),
        json_tool=None,
    )


def _registry(perms: ToolPermissions | None) -> AgentRegistry:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="a", description="d"),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="p",
        extra_tools=[_bash_tool("timer", "uv run scripts/time_tool.py *")],
        tool_permissions=perms,
    )
    aid = reg.register_agent("a", agent, ModelParameters(model_name="m"))
    reg.register_template(TemplateTree(
        name="t", slots=[TemplateSlot(name="primary", default_agent_id=aid)]))
    reg.create_compilation_config(CompilationConfig(name="c", template_name="t"))
    return reg


def _settings(target: Path) -> dict:
    return json.loads((target / ".claude" / "settings.json").read_text())


def test_bash_rule_conversion() -> None:
    assert _claude_bash_rule("uv run scripts/x.py *") == "Bash(uv run scripts/x.py:*)"
    assert _claude_bash_rule("git status") == "Bash(git status)"


def test_settings_json_carries_bash_allowlist(tmp_target: Path) -> None:
    build(tmp_target, _registry(None), "c", dialect="claude")
    perms = _settings(tmp_target)["permissions"]
    assert "Bash(uv run scripts/time_tool.py:*)" in perms["allow"]
    # No explicit tool_permissions anywhere → no blanket denials.
    assert perms["deny"] == []


def test_settings_json_allows_declared_capabilities(tmp_target: Path) -> None:
    build(tmp_target, _registry(ToolPermissions(read=True, write=True)), "c",
          dialect="claude")
    perms = _settings(tmp_target)["permissions"]
    assert "Read" in perms["allow"]
    assert "Write" in perms["allow"]
    # edit was declared-and-denied by every explicit agent.
    assert "Edit" in perms["deny"]


def test_settings_json_denies_uniformly_denied_capabilities(tmp_target: Path) -> None:
    build(tmp_target, _registry(ToolPermissions(read=True)), "c", dialect="claude")
    perms = _settings(tmp_target)["permissions"]
    assert "Read" in perms["allow"]
    assert "Write" in perms["deny"]
    assert "Edit" in perms["deny"]


def test_opencode_dialect_does_not_emit_claude_settings(tmp_target: Path) -> None:
    build(tmp_target, _registry(None), "c", dialect="opencode")
    assert not (tmp_target / ".claude").exists()
