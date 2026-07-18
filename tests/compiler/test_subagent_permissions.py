"""Permission generation when an agent has subagents / tool_permissions."""

from __future__ import annotations

from open_agent_compiler.compiler.dialects.opencode.compile_permissions import generate_permissions
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    MCPServerDefinition,
    ModelParameters,
    ToolPermissions,
)


def _variant(
    *, subagents=None, tool_permissions=None, mode="primary",
    mcp_servers=None,
) -> AgentVariant:
    return AgentVariant(
        postfix="", agent_mode=mode,
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="x", name="orch", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            subagents=subagents or [],
            tool_permissions=tool_permissions,
            mcp_servers=mcp_servers or [],
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )


def test_no_subagents_task_stays_disabled() -> None:
    out = generate_permissions(_variant())
    assert "task" not in out["permission"]
    assert out["tool"]["task"] is False


def test_subagent_children_enable_task_tool() -> None:
    subs = [
        AgentHeader(agent_id="s1", name="summarizer",
                    description="d", mode="subagent"),
    ]
    out = generate_permissions(_variant(subagents=subs))
    assert out["permission"]["task"] == "allow"
    assert out["tool"]["task"] is True


def test_primary_mode_subagents_dont_enable_task() -> None:
    # Primary-mode 'subagents' use opencode_manager via bash, not Task.
    subs = [
        AgentHeader(agent_id="p1", name="workflows/big",
                    description="d", mode="primary"),
    ]
    out = generate_permissions(_variant(subagents=subs))
    assert "task" not in out["permission"]
    assert out["tool"]["task"] is False


def test_mixed_subagent_modes_still_enable_task_for_task_kids() -> None:
    subs = [
        AgentHeader(agent_id="s1", name="quick",
                    description="d", mode="subagent"),
        AgentHeader(agent_id="p1", name="workflows/big",
                    description="d", mode="primary"),
    ]
    out = generate_permissions(_variant(subagents=subs))
    assert out["permission"]["task"] == "allow"


def test_tool_permissions_read_enables_read_in_both_blocks() -> None:
    out = generate_permissions(_variant(
        tool_permissions=ToolPermissions(read=True),
    ))
    assert out["permission"]["read"] == "allow"
    assert out["tool"]["read"] is True


def test_tool_permissions_write_edit_mcp_all_routed_correctly() -> None:
    out = generate_permissions(_variant(
        tool_permissions=ToolPermissions(write=True, edit=True, mcp=True),
    ))
    assert out["permission"]["write"] == "allow"
    assert out["permission"]["edit"] == "allow"
    assert out["permission"]["mcp"] == "allow"
    assert out["tool"]["write"] is True
    assert out["tool"]["edit"] is True
    assert out["tool"]["mcp"] is True


def test_tool_permissions_off_by_default_still_emit_false_in_tool_block() -> None:
    out = generate_permissions(_variant(
        tool_permissions=ToolPermissions(),  # all False
    ))
    # No allow entries in the permission block.
    for key in ("read", "write", "edit", "mcp"):
        assert key not in out["permission"], f"unexpected {key} in permission"
        assert out["tool"][key] is False


def _variant_with_workflow(
    *, mode="primary", todo_mode="strict",
) -> AgentVariant:
    from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition
    return AgentVariant(
        postfix="", agent_mode=mode,
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="x", name="x", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            workflow=[WorkflowStepDefinition(id=1, name="step")],
            todo_mode=todo_mode,
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )


def test_primary_workflow_strict_enables_todoread_todowrite() -> None:
    out = generate_permissions(
        _variant_with_workflow(mode="primary", todo_mode="strict"),
    )
    assert out["permission"]["todoread"] == "allow"
    assert out["permission"]["todowrite"] == "allow"
    assert out["tool"]["todoread"] is True
    assert out["tool"]["todowrite"] is True


def test_primary_workflow_lazy_also_enables_todo_tools() -> None:
    out = generate_permissions(
        _variant_with_workflow(mode="primary", todo_mode="lazy"),
    )
    assert out["permission"]["todoread"] == "allow"
    assert out["permission"]["todowrite"] == "allow"


def test_primary_workflow_none_keeps_todo_tools_disabled() -> None:
    out = generate_permissions(
        _variant_with_workflow(mode="primary", todo_mode="none"),
    )
    assert "todoread" not in out["permission"]
    assert "todowrite" not in out["permission"]


def test_subagent_workflow_does_not_enable_primary_todo_tools() -> None:
    # Subagent mode uses subagent_todo.py via bash instead.
    out = generate_permissions(
        _variant_with_workflow(mode="subagent", todo_mode="strict"),
    )
    assert "todoread" not in out["permission"]
    assert "todowrite" not in out["permission"]


def test_no_workflow_keeps_todo_tools_disabled() -> None:
    out = generate_permissions(_variant())
    assert "todoread" not in out["permission"]
    assert "todowrite" not in out["permission"]


def test_primary_mode_subagents_emit_bash_allowlist_for_opencode_manager() -> None:
    subs = [
        AgentHeader(agent_id="w", name="worker",
                    description="d", mode="primary"),
    ]
    out = generate_permissions(_variant(subagents=subs))
    bash = out["permission"]["bash"]
    assert "uv run scripts/opencode_manager.py run --agent *" in bash
    assert bash["uv run scripts/opencode_manager.py run --agent *"] == "allow"


def test_task_subagents_do_not_emit_opencode_manager_pattern() -> None:
    subs = [
        AgentHeader(agent_id="s", name="sub",
                    description="d", mode="subagent"),
    ]
    out = generate_permissions(_variant(subagents=subs))
    bash = out["permission"].get("bash", {})
    assert "uv run scripts/opencode_manager.py run --agent *" not in bash


def test_mixed_subagent_modes_emit_both_paths() -> None:
    subs = [
        AgentHeader(agent_id="s", name="quick", description="d", mode="subagent"),
        AgentHeader(agent_id="p", name="worker", description="d", mode="primary"),
    ]
    out = generate_permissions(_variant(subagents=subs))
    # Task tool for the subagent-mode child.
    assert out["permission"]["task"] == "allow"
    # Bash dispatcher for the primary-mode child.
    bash = out["permission"]["bash"]
    assert "uv run scripts/opencode_manager.py run --agent *" in bash


# ---- MCP per-server allowlists ----------------------------------------


def test_no_mcp_servers_keeps_mcp_off() -> None:
    out = generate_permissions(_variant())
    assert "mcp" not in out["permission"]
    assert out["tool"]["mcp"] is False


def test_single_mcp_server_unrestricted_emits_allow() -> None:
    out = generate_permissions(_variant(
        mcp_servers=[MCPServerDefinition(name="slack")],
    ))
    assert out["permission"]["mcp"] == {"slack": "allow"}
    # After f89a045: opencode's `tool:` block is an enable/disable switch
    # (booleans), not a permission map — granular allowlists live only in
    # `permission:`. Nested dicts get collapsed to True so opencode >=1.17
    # doesn't silently strip the tool.
    assert out["tool"]["mcp"] is True


def test_mcp_server_with_allowed_tools_emits_per_tool_block() -> None:
    out = generate_permissions(_variant(
        mcp_servers=[
            MCPServerDefinition(
                name="github",
                allowed_tools=["read_pr", "list_issues"],
            ),
        ],
    ))
    block = out["permission"]["mcp"]["github"]
    assert block["*"] == "deny"
    assert block["read_pr"] == "allow"
    assert block["list_issues"] == "allow"


def test_two_agents_with_different_mcp_servers_emit_independently() -> None:
    """Two agents in the same compile carry independent MCP allowlists."""
    a = generate_permissions(_variant(
        mcp_servers=[MCPServerDefinition(name="slack")],
    ))
    b = generate_permissions(_variant(
        mcp_servers=[MCPServerDefinition(name="github")],
    ))
    assert a["permission"]["mcp"] == {"slack": "allow"}
    assert b["permission"]["mcp"] == {"github": "allow"}
    assert "github" not in a["permission"]["mcp"]
    assert "slack" not in b["permission"]["mcp"]


def test_boolean_mcp_toggle_plus_servers_replaces_boolean() -> None:
    """When both the boolean mcp toggle and server inventory are set,
    the per-server block wins (servers are more specific)."""
    out = generate_permissions(_variant(
        tool_permissions=ToolPermissions(mcp=True),
        mcp_servers=[MCPServerDefinition(name="slack")],
    ))
    # The per-server dict supersedes the catch-all 'allow' string.
    assert out["permission"]["mcp"] == {"slack": "allow"}


def test_boolean_mcp_toggle_alone_still_emits_allow_string() -> None:
    """Legacy behaviour preserved when no server inventory is declared."""
    out = generate_permissions(_variant(
        tool_permissions=ToolPermissions(mcp=True),
    ))
    assert out["permission"]["mcp"] == "allow"
    assert out["tool"]["mcp"] is True


def test_multiple_mcp_servers_emit_all_independently() -> None:
    out = generate_permissions(_variant(
        mcp_servers=[
            MCPServerDefinition(name="slack"),
            MCPServerDefinition(
                name="github", allowed_tools=["read_pr"],
            ),
            MCPServerDefinition(name="linear"),
        ],
    ))
    mcp_perm = out["permission"]["mcp"]
    assert mcp_perm["slack"] == "allow"
    assert mcp_perm["linear"] == "allow"
    assert mcp_perm["github"]["read_pr"] == "allow"
    assert mcp_perm["github"]["*"] == "deny"
