"""Tests for the compiler module."""

import warnings

import pytest

from open_agent_compiler._types import (
    ActionDefinition,
    AgentDefinition,
    AgentPermissions,
    SkillDefinition,
    SubagentDefinition,
    ToolDefinition,
    ToolPermissions,
)
from open_agent_compiler.compiler import compile_agent


def _make_tool(name: str, *, script: str | None = None) -> ToolDefinition:
    script = script or f"{name}.py"
    return ToolDefinition(
        name=name,
        description=f"Tool {name}",
        actions=(
            ActionDefinition(
                command_pattern=f"uv run scripts/{script} *",
                description=f"Run {name}",
                usage_example=f"uv run scripts/{script} --arg val",
            ),
        ),
        script_files=(script,),
    )


class TestCompiler:
    def test_opencode_output_structure(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent, target="opencode")
        assert result["backend"] == "opencode"
        assert result["agent"]["name"] == "test-agent"
        assert "config" in result
        assert result["config"]["$schema"] == "https://opencode.ai/config.json"
        assert result["config"]["model"] == "anthropic/sonnet"
        assert result["skills"] == []

    def test_config_has_provider_hierarchy(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        config = result["config"]
        assert "provider" in config
        assert "anthropic" in config["provider"]
        prov = config["provider"]["anthropic"]
        assert "models" in prov
        assert "sonnet" in prov["models"]
        assert prov["models"]["sonnet"]["id"] == "claude-sonnet-4-5-20250929"

    def test_config_has_no_agent_section(self, sample_agent: AgentDefinition):
        """opencode.json (config) does not contain per-agent fields."""
        result = compile_agent(sample_agent)
        assert "agent" not in result["config"]

    def test_config_has_compaction(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        config = result["config"]
        assert config["compaction"] == {"auto": True, "prune": True}

    def test_tool_is_permission_dict(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        tool = result["tool"]
        assert isinstance(tool, dict)
        assert "bash" in tool
        bash = tool["bash"]
        assert bash["*"] == "deny"
        assert bash["uv run scripts/read_file.py *"] == "allow"

    def test_auto_permissions_include_bool_fields(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        tool = result["tool"]
        assert tool["read"] is False
        assert tool["write"] is False
        assert tool["edit"] is False
        assert tool["task"] is False
        assert tool["todoread"] is False
        assert tool["todowrite"] is False

    def test_scripts_list(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        assert "scripts" in result
        assert "read_file.py" in result["scripts"]

    def test_default_target_is_opencode(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        assert result["backend"] == "opencode"

    def test_unknown_target_raises(self, sample_agent: AgentDefinition):
        with pytest.raises(ValueError, match="Unknown target"):
            compile_agent(sample_agent, target="unknown")

    def test_skills_with_tool_docs(self, sample_agent: AgentDefinition):
        tool = _make_tool("grep", script="grep.py")
        skill = SkillDefinition(
            name="security-review",
            description="Review for security issues",
            instructions="Check OWASP top 10.",
            tools=(tool,),
        )
        agent_with_skills = AgentDefinition(
            name=sample_agent.name,
            description=sample_agent.description,
            config=sample_agent.config,
            tools=sample_agent.tools,
            skills=(skill,),
            skill_instructions=(("security-review", "Use for security audits"),),
            system_prompt=sample_agent.system_prompt,
        )
        result = compile_agent(agent_with_skills)
        assert len(result["skills"]) == 1
        s = result["skills"][0]
        assert s["name"] == "security-review"
        assert s["tools"] == ["grep"]
        assert "## Available Tools" in s["instructions"]
        assert "### grep" in s["instructions"]
        assert "uv run scripts/grep.py" in s["instructions"]

    def test_no_duplicate_bash_permissions(self):
        """Shared tools produce one permission entry."""
        tool = _make_tool("shared")
        skill = SkillDefinition(
            name="my-skill",
            description="A skill",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            tools=(tool,),
            skills=(skill,),
            skill_instructions=(("my-skill", "Use it"),),
        )
        result = compile_agent(agent)
        bash = result["tool"]["bash"]
        allow_keys = [k for k, v in bash.items() if v == "allow"]
        assert len(allow_keys) == 1

    def test_auto_skill_permissions(self):
        """Auto-generated permissions include skill allow/deny."""
        tool = _make_tool("x")
        skill = SkillDefinition(
            name="data-query",
            description="Query data",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("data-query", "Use for data"),),
        )
        result = compile_agent(agent)
        assert "skill" in result["tool"]
        assert result["tool"]["skill"]["data-query"] == "allow"
        assert result["tool"]["skill"]["*"] == "deny"

    def test_explicit_tool_permissions(self):
        """Explicit ToolPermissions override auto-generation."""
        perms = ToolPermissions(
            bash=(("uv run scripts/custom.py *", "allow"), ("*", "deny")),
            read=True,
            write=True,
            edit=False,
            task=False,
            skill=(("my-skill", "allow"), ("*", "deny")),
            mcp=(("zai-mcp-*", False),),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            tool_permissions=perms,
        )
        result = compile_agent(agent)
        tool = result["tool"]
        assert tool["bash"]["uv run scripts/custom.py *"] == "allow"
        assert tool["read"] is True
        assert tool["write"] is True
        assert tool["skill"]["my-skill"] == "allow"
        assert tool["zai-mcp-*"] is False

    def test_agent_permissions(self):
        """AgentPermissions compile into permission: section."""
        perms = AgentPermissions(
            doom_loop="allow",
            task=((".opencode/agents/*.md", "allow"),),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            permissions=perms,
        )
        result = compile_agent(agent)
        assert "permission" in result
        assert result["permission"]["doom_loop"] == "allow"
        assert result["permission"]["task"][".opencode/agents/*.md"] == "allow"

    def test_doom_loop_baseline_when_no_permissions(
        self, sample_agent: AgentDefinition
    ):
        """Always generates doom_loop baseline even without explicit permissions."""
        result = compile_agent(sample_agent)
        assert "permission" in result
        assert result["permission"]["doom_loop"] == "deny"

    def test_mode_in_agent_section(self):
        agent = AgentDefinition(
            name="test",
            description="test",
            mode="primary",
        )
        result = compile_agent(agent)
        assert result["agent"]["mode"] == "primary"

    def test_no_mode_when_empty(self, sample_agent: AgentDefinition):
        result = compile_agent(sample_agent)
        assert "mode" not in result["agent"]

    def test_deny_first_in_bash(self, sample_agent: AgentDefinition):
        """'*': 'deny' must be first key in auto-generated bash perms."""
        result = compile_agent(sample_agent)
        bash_keys = list(result["tool"]["bash"].keys())
        assert bash_keys[0] == "*"

    def test_deny_first_in_skill(self):
        """'*': 'deny' must be first key in auto-generated skill perms."""
        tool = _make_tool("x")
        skill = SkillDefinition(
            name="data-query",
            description="Query data",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("data-query", "Use for data"),),
        )
        result = compile_agent(agent)
        skill_keys = list(result["tool"]["skill"].keys())
        assert skill_keys[0] == "*"

    def test_enriched_skill_instructions(self):
        """skill_instructions compile into enriched dicts with tool descriptions."""
        tool = _make_tool("db_query")
        skill = SkillDefinition(
            name="data-query",
            description="Query data",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("data-query", "Use when querying data"),),
        )
        result = compile_agent(agent)
        assert "skill_instructions" in result
        si = result["skill_instructions"]
        assert len(si) == 1
        assert si[0]["name"] == "data-query"
        assert si[0]["instruction"] == "Use when querying data"
        assert len(si[0]["tools"]) == 1
        assert si[0]["tools"][0]["name"] == "db_query"
        assert si[0]["tools"][0]["description"] == "Tool db_query"

    def test_skill_instructions_no_tools(self):
        """Skill instructions with no tools have empty tools list."""
        skill = SkillDefinition(
            name="review",
            description="Review code",
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("review", "Use when reviewing PRs"),),
        )
        result = compile_agent(agent)
        si = result["skill_instructions"]
        assert si[0]["tools"] == []

    def test_no_skill_instructions_key_when_empty(self, sample_agent: AgentDefinition):
        """No skill_instructions key when none defined."""
        result = compile_agent(sample_agent)
        assert "skill_instructions" not in result

    def test_config_no_provider_when_empty(self):
        """No provider key in config when no providers configured."""
        agent = AgentDefinition(name="test", description="test")
        result = compile_agent(agent)
        assert "provider" not in result["config"]

    def test_config_no_model_when_empty(self):
        """No model key in config when no default_model set."""
        agent = AgentDefinition(name="test", description="test")
        result = compile_agent(agent)
        assert "model" not in result["config"]

    def test_agent_section_variant(self):
        agent = AgentDefinition(name="test", description="test", variant="fast")
        result = compile_agent(agent)
        assert result["agent"]["variant"] == "fast"

    def test_agent_section_temperature(self):
        agent = AgentDefinition(name="test", description="test", temperature=0.7)
        result = compile_agent(agent)
        assert result["agent"]["temperature"] == 0.7

    def test_agent_section_top_p(self):
        agent = AgentDefinition(name="test", description="test", top_p=0.9)
        result = compile_agent(agent)
        assert result["agent"]["top_p"] == 0.9

    def test_agent_section_hidden(self):
        agent = AgentDefinition(name="test", description="test", hidden=True)
        result = compile_agent(agent)
        assert result["agent"]["hidden"] is True

    def test_agent_section_hidden_default_omitted(self):
        agent = AgentDefinition(name="test", description="test")
        result = compile_agent(agent)
        assert "hidden" not in result["agent"]

    def test_agent_section_color(self):
        agent = AgentDefinition(name="test", description="test", color="#FF5733")
        result = compile_agent(agent)
        assert result["agent"]["color"] == "#FF5733"

    def test_agent_section_steps(self):
        agent = AgentDefinition(name="test", description="test", steps=50)
        result = compile_agent(agent)
        assert result["agent"]["steps"] == 50

    def test_agent_section_steps_zero_omitted(self):
        agent = AgentDefinition(name="test", description="test")
        result = compile_agent(agent)
        assert "steps" not in result["agent"]

    def test_agent_section_options(self):
        agent = AgentDefinition(
            name="test",
            description="test",
            options=(("reasoning_effort", "high"), ("cache", True)),
        )
        result = compile_agent(agent)
        opts = result["agent"]["options"]
        assert opts["reasoning_effort"] == "high"
        assert opts["cache"] is True

    def test_agent_section_temperature_none_omitted(self):
        """temperature=None (default) is not emitted."""
        agent = AgentDefinition(name="test", description="test")
        result = compile_agent(agent)
        assert "temperature" not in result["agent"]

    def test_subagent_section_appears_when_subagents_exist(self):
        """Auto-generated subagent section is appended to system prompt."""
        subs = (
            SubagentDefinition(
                name="persona/quick_ack",
                description="Quick acknowledgment",
                notes="Sends immediate response and routing decision.",
            ),
            SubagentDefinition(
                name="persona/thinking",
                description="Mental processes",
            ),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            system_prompt="You are a test agent.",
            subagents=subs,
        )
        result = compile_agent(agent)
        prompt = result["agent"]["system_prompt"]
        assert "## Available Subagents" in prompt
        assert "### persona/quick_ack — Quick acknowledgment" in prompt
        assert "Sends immediate response and routing decision." in prompt
        assert "### persona/thinking — Mental processes" in prompt

    def test_subagent_section_absent_when_no_subagents(self):
        """No subagent section when no subagents defined."""
        agent = AgentDefinition(
            name="test",
            description="test",
            system_prompt="You are a test agent.",
        )
        result = compile_agent(agent)
        prompt = result["agent"]["system_prompt"]
        assert "## Available Subagents" not in prompt


class TestWorkspace:
    def test_workspace_adds_bash_pattern(self):
        """Workspace adds workspace_io.py pattern to bash permissions."""
        agent = AgentDefinition(
            name="my-agent",
            description="test",
            workspace=".agent_workspace/{name}",
        )
        result = compile_agent(agent)
        bash = result["tool"]["bash"]
        pattern = (
            "uv run scripts/workspace_io.py --workspace .agent_workspace/my-agent *"
        )
        assert pattern in bash
        assert bash[pattern] == "allow"

    def test_workspace_keeps_write_false(self):
        """Workspace does NOT enable write: true."""
        agent = AgentDefinition(
            name="test",
            description="test",
            workspace=".agent_workspace/test",
        )
        result = compile_agent(agent)
        assert result["tool"]["write"] is False
        assert result["tool"]["edit"] is False

    def test_workspace_write_mutual_exclusion(self):
        """write=True + workspace raises ValueError."""
        agent = AgentDefinition(
            name="test",
            description="test",
            workspace=".agent_workspace/test",
            tool_permissions=ToolPermissions(write=True),
        )
        with pytest.raises(ValueError, match="mutually exclusive"):
            compile_agent(agent)

    def test_security_policy_in_prompt(self):
        """Compiled prompt contains SECURITY POLICY section."""
        agent = AgentDefinition(
            name="test",
            description="test",
            system_prompt="You are a test agent.",
        )
        result = compile_agent(agent)
        prompt = result["agent"]["system_prompt"]
        assert "## SECURITY POLICY" in prompt
        assert "### ALLOWED actions" in prompt
        assert "### FORBIDDEN" in prompt

    def test_security_policy_lists_workspace(self):
        """Security policy mentions workspace path when set."""
        agent = AgentDefinition(
            name="test",
            description="test",
            workspace=".agent_workspace/test",
        )
        result = compile_agent(agent)
        prompt = result["agent"]["system_prompt"]
        assert "workspace_io.py" in prompt
        assert ".agent_workspace/test" in prompt

    def test_security_policy_lists_allowed_tools(self):
        """Policy section lists the agent's actual skills and subagents."""
        tool = _make_tool("x")
        skill = SkillDefinition(
            name="data-query",
            description="Query data",
            tools=(tool,),
        )
        sub = SubagentDefinition(
            name="helper/sub1",
            description="A helper",
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("data-query", "Use for data"),),
            subagents=(sub,),
        )
        result = compile_agent(agent)
        prompt = result["agent"]["system_prompt"]
        assert "`data-query`" in prompt
        assert "`helper/sub1`" in prompt

    def test_write_true_without_workspace_warns(self):
        """write=True without workspace emits a warning."""
        agent = AgentDefinition(
            name="test",
            description="test",
            tool_permissions=ToolPermissions(write=True),
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            compile_agent(agent)
            assert len(w) == 1
            assert "write=True without a workspace" in str(w[0].message)

    def test_workspace_adds_script_to_list(self):
        """Workspace adds workspace_io.py to the scripts list."""
        agent = AgentDefinition(
            name="test",
            description="test",
            workspace=".agent_workspace/test",
        )
        result = compile_agent(agent)
        assert "workspace_io.py" in result["scripts"]

    def test_workspace_resolves_name_placeholder(self):
        """The {name} placeholder in workspace is resolved to agent name."""
        agent = AgentDefinition(
            name="my-agent",
            description="test",
            workspace=".agent_workspace/{name}",
        )
        result = compile_agent(agent)
        bash = result["tool"]["bash"]
        pattern = (
            "uv run scripts/workspace_io.py --workspace .agent_workspace/my-agent *"
        )
        assert pattern in bash

    def test_default_deny_skill_when_no_skills(self):
        """skill: false when no skills are defined."""
        agent = AgentDefinition(name="test", description="test")
        result = compile_agent(agent)
        assert result["tool"]["skill"] is False

    def test_default_deny_mcp(self):
        """mcp: false is always emitted."""
        agent = AgentDefinition(name="test", description="test")
        result = compile_agent(agent)
        assert result["tool"]["mcp"] is False

    def test_default_deny_mcp_with_skills(self):
        """mcp: false even when skills exist."""
        tool = _make_tool("x")
        skill = SkillDefinition(
            name="my-skill",
            description="test",
            tools=(tool,),
        )
        agent = AgentDefinition(
            name="test",
            description="test",
            skills=(skill,),
            skill_instructions=(("my-skill", "Use it"),),
        )
        result = compile_agent(agent)
        assert result["tool"]["mcp"] is False

    def test_security_policy_forbids_skills_when_none(self):
        """Security policy says skills are disabled when none defined."""
        agent = AgentDefinition(name="test", description="test")
        result = compile_agent(agent)
        prompt = result["agent"]["system_prompt"]
        assert "all skills are disabled" in prompt

    def test_security_policy_forbids_mcp(self):
        """Security policy always says MCP is disabled."""
        agent = AgentDefinition(name="test", description="test")
        result = compile_agent(agent)
        prompt = result["agent"]["system_prompt"]
        assert "MCP tools" in prompt

    def test_security_policy_session_isolation(self):
        """Security policy mentions session isolation when workspace is set."""
        agent = AgentDefinition(
            name="test",
            description="test",
            workspace=".agent_workspace/test",
        )
        result = compile_agent(agent)
        prompt = result["agent"]["system_prompt"]
        assert "--run-id" in prompt
        assert "init" in prompt
