"""Tests for the Codex dialect compiler.

Verifies that the CodexCompiler generates correct `.codex/agents/*.toml`
files — parseable TOML with the required name/description/
developer_instructions fields — plus the AGENTS.md index.
"""

from __future__ import annotations

import tomllib
import warnings
from pathlib import Path

import pytest

from open_agent_compiler.compiler.compile import build
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    MCPServerDefinition,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
    ToolPermissions,
    WorkflowStepDefinition,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry


def _register_single(reg: AgentRegistry, agent: AgentDefinition, *, slot: str = "primary") -> None:
    agent_id = reg.register_agent(
        agent.header.name, agent,
        ModelParameters(model_name="gpt-5.2", temperature=0.3),
    )
    reg.register_template(
        TemplateTree(name="tpl", slots=[TemplateSlot(name=slot, default_agent_id=agent_id)])
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))


def _minimal_codex_factory() -> AgentRegistry:
    """Factory for a minimal codex agent (no workflow, no subagents)."""
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="greeter",
            name="greeter",
            description="A friendly greeter.",
        ),
        usage_explanation_long="Greets users warmly.",
        usage_explanation_short="greets",
        system_prompt="You are a friendly greeter. Reply in one sentence.",
    )
    _register_single(reg, agent)
    return reg


def _workflow_codex_factory() -> AgentRegistry:
    """Factory for a codex agent with workflow and subagents."""
    reg = AgentRegistry()

    sub_agent = AgentDefinition(
        header=AgentHeader(
            agent_id="helper",
            name="helper",
            description="A helpful assistant.",
        ),
        usage_explanation_long="Helps with tasks.",
        usage_explanation_short="helps",
        system_prompt="You are helpful.",
    )
    sub_id = reg.register_agent(
        "helper", sub_agent,
        ModelParameters(model_name="gpt-5.2", temperature=0.5),
    )

    orchestrator = AgentDefinition(
        header=AgentHeader(
            agent_id="orch",
            name="orchestrator",
            description="Orchestrates tasks.",
        ),
        usage_explanation_long="Delegates to helper.",
        usage_explanation_short="delegates",
        subagents=[
            AgentHeader(
                agent_id="helper",
                name="helper",
                description="A helpful assistant.",
                mode="subagent",
            )
        ],
        workflow=[
            WorkflowStepDefinition(
                id=1,
                name="Delegate",
                instructions="Spawn the helper subagent.",
                subagents=("helper",),
            ),
        ],
        system_prompt="You orchestrate.",
    )
    orch_id = reg.register_agent(
        "orch", orchestrator,
        ModelParameters(model_name="gpt-5.2", temperature=0.2),
    )

    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[
                TemplateSlot(name="primary", default_agent_id=orch_id),
                TemplateSlot(name="helper", default_agent_id=sub_id),
            ],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
    return reg


def _load(tmp_target: Path, name: str) -> dict:
    raw = (tmp_target / ".codex" / "agents" / f"{name}.toml").read_text()
    return tomllib.loads(raw)


# ---- Basic compilation ------------------------------------------------


def test_codex_compile_writes_codex_agents_dir(tmp_target: Path) -> None:
    """Codex compiler writes to .codex/agents/ not .opencode/agents/."""
    build(tmp_target, _minimal_codex_factory(), "prod", dialect="codex")
    assert (tmp_target / ".codex" / "agents" / "primary.toml").exists()
    assert not (tmp_target / ".opencode").exists()


def test_codex_compile_produces_valid_toml(tmp_target: Path) -> None:
    build(tmp_target, _minimal_codex_factory(), "prod", dialect="codex")
    data = _load(tmp_target, "primary")
    assert data["name"] == "primary"
    assert data["description"] == "A friendly greeter."
    assert data["model"] == "gpt-5.2"
    assert "friendly greeter" in data["developer_instructions"]


def test_codex_default_sandbox_is_workspace_write(tmp_target: Path) -> None:
    """tool_permissions=None keeps codex's workspace-write default."""
    build(tmp_target, _minimal_codex_factory(), "prod", dialect="codex")
    assert _load(tmp_target, "primary")["sandbox_mode"] == "workspace-write"


def test_codex_readonly_sandbox_from_permissions(tmp_target: Path) -> None:
    """Explicit permissions without write/edit collapse to read-only."""
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="auditor", description="Audits."),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="Audit things.",
        tool_permissions=ToolPermissions(read=True),
    )
    _register_single(reg, agent)
    build(tmp_target, reg, "prod", dialect="codex")
    data = _load(tmp_target, "primary")
    assert data["sandbox_mode"] == "read-only"
    # Explicit permissions also produce a SECURITY POLICY block
    assert "SECURITY POLICY" in data["developer_instructions"]
    assert "write access is disabled" in data["developer_instructions"]


def test_codex_write_permission_keeps_workspace_write(tmp_target: Path) -> None:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="writer", description="Writes."),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="Write things.",
        tool_permissions=ToolPermissions(read=True, write=True),
    )
    _register_single(reg, agent)
    build(tmp_target, reg, "prod", dialect="codex")
    assert _load(tmp_target, "primary")["sandbox_mode"] == "workspace-write"


# ---- Workflow + subagents ---------------------------------------------


def test_codex_workflow_rendered_into_instructions(tmp_target: Path) -> None:
    build(tmp_target, _workflow_codex_factory(), "prod", dialect="codex")
    body = _load(tmp_target, "primary")["developer_instructions"]
    assert "## Workflow" in body
    assert "### Step 1: Delegate" in body
    assert "TODO.md" in body  # strict todo_mode default
    assert "## Final Checklist" in body


def test_codex_subagents_use_delegation_not_agent_tool(tmp_target: Path) -> None:
    """Codex has no Agent() spawn tool — delegation is natural language."""
    build(tmp_target, _workflow_codex_factory(), "prod", dialect="codex")
    body = _load(tmp_target, "primary")["developer_instructions"]
    assert "## Available Subagents" in body
    assert "**helper**" in body
    assert "Agent({" not in body


def test_codex_both_slots_compiled(tmp_target: Path) -> None:
    build(tmp_target, _workflow_codex_factory(), "prod", dialect="codex")
    assert (tmp_target / ".codex" / "agents" / "primary.toml").exists()
    assert (tmp_target / ".codex" / "agents" / "helper.toml").exists()


def test_codex_agents_md_index_written(tmp_target: Path) -> None:
    build(tmp_target, _workflow_codex_factory(), "prod", dialect="codex")
    index = (tmp_target / "AGENTS.md").read_text()
    assert "primary" in index
    assert "helper" in index
    assert "Orchestrates tasks." in index


# ---- MCP servers -------------------------------------------------------


def test_codex_url_mcp_server_emitted(tmp_target: Path) -> None:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="mcpuser", description="Uses MCP."),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="Use the docs server.",
        mcp_servers=[MCPServerDefinition(name="docs", url="https://mcp.example/sse")],
    )
    _register_single(reg, agent)
    build(tmp_target, reg, "prod", dialect="codex")
    data = _load(tmp_target, "primary")
    assert data["mcp_servers"]["docs"]["url"] == "https://mcp.example/sse"


def test_codex_stdio_mcp_server_warns(tmp_target: Path) -> None:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="mcpuser", description="Uses MCP."),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="Use the local server.",
        mcp_servers=[MCPServerDefinition(name="local")],
    )
    _register_single(reg, agent)
    with pytest.warns(UserWarning, match="stdio"):
        build(tmp_target, reg, "prod", dialect="codex")
    data = _load(tmp_target, "primary")
    assert "mcp_servers" not in data


# ---- TOML escaping edge cases -----------------------------------------


def test_codex_instructions_with_quotes_and_backslashes_roundtrip(
    tmp_target: Path,
) -> None:
    """Prompts containing triple quotes and backslashes must survive TOML."""
    nasty = 'Use """triple quotes""" and C:\\paths\\like\\this. End with "'
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="nasty", description="Edge cases."),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt=nasty,
    )
    _register_single(reg, agent)
    build(tmp_target, reg, "prod", dialect="codex")
    body = _load(tmp_target, "primary")["developer_instructions"]
    assert nasty in body


def test_codex_no_warnings_for_plain_agent(tmp_target: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        build(tmp_target, _minimal_codex_factory(), "prod", dialect="codex")
