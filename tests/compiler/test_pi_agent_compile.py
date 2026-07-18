"""Tests for the Pi agent dialect compiler.

Verifies that the PiAgentCompiler generates correct `.pi/agents/*.md`
files with proper YAML frontmatter and markdown body.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from open_agent_compiler.compiler.script import CompileScript
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
    WorkflowStepDefinition,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry


def _minimal_pi_factory() -> AgentRegistry:
    """Factory for a minimal pi agent (no workflow, no subagents)."""
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
    agent_id = reg.register_agent(
        "greeter", agent,
        ModelParameters(model_name="anthropic/claude-haiku-4-5-20251001", temperature=0.7),
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
    return reg


def _workflow_pi_factory() -> AgentRegistry:
    """Factory for a pi agent with workflow and subagents."""
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
        ModelParameters(model_name="anthropic/claude-haiku-4-5-20251001", temperature=0.5),
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
        ModelParameters(model_name="anthropic/claude-sonnet-4-20250514", temperature=0.2),
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


# ---- Basic compilation ------------------------------------------------


def test_pi_compile_writes_pi_agents_dir(tmp_target: Path) -> None:
    """Pi compiler writes to .pi/agents/ not .opencode/agents/."""
    build(
        tmp_target, _minimal_pi_factory(), "prod", dialect="pi",
    )
    assert (tmp_target / ".pi" / "agents" / "primary.md").exists()
    assert not (tmp_target / ".opencode").exists()


def test_pi_compile_produces_valid_yaml_frontmatter(tmp_target: Path) -> None:
    """Generated .md files have parseable YAML frontmatter."""
    build(
        tmp_target, _minimal_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    # Extract YAML between --- markers
    parts = content.split("---")
    assert len(parts) >= 3, "Expected YAML frontmatter delimited by ---"
    frontmatter = yaml.safe_load(parts[1])
    assert isinstance(frontmatter, dict)


def test_pi_compile_frontmatter_has_required_fields(tmp_target: Path) -> None:
    """Frontmatter includes description, model, tools, prompt_mode."""
    build(
        tmp_target, _minimal_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    parts = content.split("---")
    frontmatter = yaml.safe_load(parts[1])

    assert "description" in frontmatter
    assert "model" in frontmatter
    assert "tools" in frontmatter
    assert "prompt_mode" in frontmatter


def test_pi_compile_model_matches_registration(tmp_target: Path) -> None:
    """Frontmatter model field matches the registered ModelParameters."""
    build(
        tmp_target, _minimal_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    parts = content.split("---")
    frontmatter = yaml.safe_load(parts[1])

    assert frontmatter["model"] == "anthropic/claude-haiku-4-5-20251001"


def test_pi_compile_body_contains_system_prompt(tmp_target: Path) -> None:
    """Markdown body includes the agent's system_prompt."""
    build(
        tmp_target, _minimal_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    assert "You are a friendly greeter" in content


# ---- Workflow rendering ----------------------------------------------


def test_pi_compile_workflow_renders_steps(tmp_target: Path) -> None:
    """Agents with workflow get rendered steps in the body."""
    build(
        tmp_target, _workflow_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    assert "## Workflow" in content
    assert "Step 1: Delegate" in content
    assert "Spawn the helper subagent" in content


def test_pi_compile_workflow_subagent_references(tmp_target: Path) -> None:
    """Workflow steps reference subagents with pi Agent() syntax."""
    build(
        tmp_target, _workflow_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    # JSON-style quoted keys (P2#6 fix)
    assert 'Agent({ "subagent_type":' in content
    assert '"helper"' in content


def test_pi_compile_available_subagents_section(tmp_target: Path) -> None:
    """Agents with subagents get an 'Available Subagents' section."""
    build(
        tmp_target, _workflow_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    assert "## Available Subagents" in content
    assert "**helper**" in content


def test_pi_compile_system_prompt_prepended_to_workflow(tmp_target: Path) -> None:
    """When both system_prompt and workflow are set, system_prompt comes first.

    Regression guard: the body builder previously took the workflow branch
    and silently dropped system_prompt. Opencode's compose_body prepends it,
    and AgentDefinition's docstring documents this contract.
    """
    build(
        tmp_target, _workflow_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    # The workflow factory's orchestrator has system_prompt="You orchestrate."
    assert "You orchestrate." in content
    # system_prompt must appear BEFORE the workflow header
    assert content.index("You orchestrate.") < content.index("## Workflow")


# ---- Tool mapping -----------------------------------------------------


def test_pi_compile_basic_tools_in_frontmatter(tmp_target: Path) -> None:
    """Minimal agents get read + bash tools by default."""
    build(
        tmp_target, _minimal_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    parts = content.split("---")
    frontmatter = yaml.safe_load(parts[1])

    tools = frontmatter["tools"]
    assert "read" in tools
    assert "bash" in tools


def test_pi_compile_task_tool_when_subagents_present(tmp_target: Path) -> None:
    """Agents with subagents get the `task` tool."""
    build(
        tmp_target, _workflow_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    parts = content.split("---")
    frontmatter = yaml.safe_load(parts[1])

    tools = frontmatter["tools"]
    assert "task" in tools


# ---- CompileScript integration ---------------------------------------


def test_compile_script_pi_dialect(tmp_target: Path) -> None:
    """CompileScript with dialect='pi' writes to .pi/agents/."""
    script = CompileScript(
        target=tmp_target,
        factory=_minimal_pi_factory,
        config="prod",
        dialect="pi",
        clean=True,
    )
    result = script.run()
    pi_agents = (tmp_target / ".pi" / "agents").glob("*.md")
    assert any(pi_agents)


def test_compile_script_pi_dialect_writes_multiple_agents(tmp_target: Path) -> None:
    """Multi-agent tree compiles all agents to .pi/agents/."""
    script = CompileScript(
        target=tmp_target,
        factory=_workflow_pi_factory,
        config="prod",
        dialect="pi",
        clean=True,
    )
    result = script.run()
    pi_agents_dir = tmp_target / ".pi" / "agents"
    md_files = list(pi_agents_dir.glob("*.md"))
    assert len(md_files) == 2  # primary + helper
    names = {p.stem for p in md_files}
    assert names == {"primary", "helper"}


# ---- Prompt mode ------------------------------------------------------


def test_pi_compile_prompt_mode_is_replace(tmp_target: Path) -> None:
    """Pi agents default to prompt_mode: replace (standalone prompt)."""
    build(
        tmp_target, _minimal_pi_factory(), "prod", dialect="pi",
    )
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    parts = content.split("---")
    frontmatter = yaml.safe_load(parts[1])

    assert frontmatter["prompt_mode"] == "replace"


# ---- Skills mapping ---------------------------------------------------


def test_pi_compile_skills_in_frontmatter(tmp_target: Path) -> None:
    """Agents with skills get them listed in frontmatter."""
    from open_agent_compiler.model.core.skills_model import SkillDefinition

    reg = AgentRegistry()
    skill = SkillDefinition(
        name="test-skill",
        description="A test skill.",
        usage_explanation_long="A test skill.",
        usage_explanation_short="test",
        rules=[],
        workflow_steps=[],
        positive_examples=[],
        negative_examples=[],
    )
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="skilled",
            name="skilled",
            description="Has skills.",
        ),
        usage_explanation_long="Uses skills.",
        usage_explanation_short="skilled",
        system_prompt="You use skills.",
        skills=[skill],
    )
    agent_id = reg.register_agent(
        "skilled", agent,
        ModelParameters(model_name="test/model", temperature=0.0),
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))

    build(tmp_target, reg, "prod", dialect="pi")
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    parts = content.split("---")
    frontmatter = yaml.safe_load(parts[1])

    assert "skills" in frontmatter
    assert "test-skill" in frontmatter["skills"]


# ---- Permissions enforcement ---------------------------------------


def test_pi_compile_respects_read_denial(tmp_target: Path) -> None:
    """When tool_permissions.read=False, read appears in disallowed_tools."""
    from open_agent_compiler.model.core.agent_model import ToolPermissions

    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="noread",
            name="NoRead",
            description="Cannot read.",
        ),
        usage_explanation_long="No read access.",
        usage_explanation_short="noread",
        system_prompt="You cannot read.",
        tool_permissions=ToolPermissions(read=False, write=True, edit=True, mcp=False),
    )
    agent_id = reg.register_agent(
        "noread", agent,
        ModelParameters(model_name="test/model", temperature=0.0),
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))

    build(tmp_target, reg, "prod", dialect="pi")
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    parts = content.split("---")
    frontmatter = yaml.safe_load(parts[1])

    assert "read" not in frontmatter.get("tools", "")
    assert "read" in frontmatter.get("disallowed_tools", "")
    assert "SECURITY POLICY" in content


def test_pi_compile_bash_always_present_with_explicit_permissions(tmp_target: Path) -> None:
    """bash is always allowed even when tool_permissions is explicit.

    Regression guard for P2: explicit tool_permissions previously dropped
    bash because there's no bash toggle in ToolPermissions. bash is the
    fundamental execution tool — pi agents need it to run scripts.
    """
    from open_agent_compiler.model.core.agent_model import ToolPermissions

    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="scripted",
            name="Scripted",
            description="Runs scripts.",
        ),
        usage_explanation_long="Runs bash scripts.",
        usage_explanation_short="scripts",
        system_prompt="You run scripts.",
        tool_permissions=ToolPermissions(read=True, write=True, edit=True, mcp=False),
    )
    agent_id = reg.register_agent(
        "scripted", agent,
        ModelParameters(model_name="test/model", temperature=0.0),
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))

    build(tmp_target, reg, "prod", dialect="pi")
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    parts = content.split("---")
    frontmatter = yaml.safe_load(parts[1])

    assert "bash" in frontmatter.get("tools", "")


def test_pi_compile_no_duplicate_in_tools_and_disallowed(tmp_target: Path) -> None:
    """A tool can't appear in both tools and disallowed_tools.

    Regression guard for P2: extra_tools/skills could re-add a denied
    built-in (e.g. a skill's workflow_steps includes a tool named 'write'
    that maps to pi's 'write'), producing contradictory frontmatter.
    """
    from open_agent_compiler.model.core.agent_model import ToolPermissions
    from open_agent_compiler.model.core.skills_model import SkillDefinition, WorkflowStep
    from open_agent_compiler.model.core.tools_model import (
        ToolDefinition, ToolDefinitionHeader, ToolDefinitionLogicBash,
    )
    from open_agent_compiler.model.core.permissions_model import BashToolPermission

    reg = AgentRegistry()
    # A skill whose workflow step uses a tool named 'write'
    write_tool = ToolDefinition(
        header=ToolDefinitionHeader(
            name="write",
            description="Write files",
            usage_explanation_long="Writes content to files",
            usage_explanation_short="writes",
            rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(tool_name="write"),
            positive_examples=["echo content > file.txt"],
            negative_examples=[],
            mode_specific_rules=[],
        ),
        json_tool=None,
        usage_explanation_long="Writes content to files",
        usage_explanation_short="writes",
    )
    skill = SkillDefinition(
        name="file-writer",
        description="Writes files",
        usage_explanation_long="Writes files via bash",
        usage_explanation_short="writes",
        rules=[],
        workflow_steps=[
            WorkflowStep(
                header="Write",
                condition=None,
                result=None,
                rule="Write the file.",
                tools_used=[write_tool],
            ),
        ],
        positive_examples=[],
        negative_examples=[],
    )
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="writer",
            name="Writer",
            description="Writes files.",
        ),
        usage_explanation_long="Writes files.",
        usage_explanation_short="writes",
        system_prompt="You write files.",
        skills=[skill],
        tool_permissions=ToolPermissions(read=True, write=False, edit=True, mcp=False),
    )
    agent_id = reg.register_agent(
        "writer", agent,
        ModelParameters(model_name="test/model", temperature=0.0),
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))

    build(tmp_target, reg, "prod", dialect="pi")
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    parts = content.split("---")
    frontmatter = yaml.safe_load(parts[1])

    tools = frontmatter.get("tools", "")
    disallowed = frontmatter.get("disallowed_tools", "")
    # write should be disallowed, not in tools
    assert "write" not in tools
    assert "write" in disallowed
    # No tool should appear in both lists
    tools_set = {t.strip() for t in tools.split(",") if t.strip()}
    disallowed_set = {t.strip() for t in disallowed.split(",") if t.strip()}
    assert tools_set.isdisjoint(disallowed_set), (
        f"Tools {tools_set & disallowed_set} appear in both lists"
    )


# Import build here to avoid circular imports
from open_agent_compiler.compiler.compile import build


# ---- Fixes from the pre-merge parity audit ---------------------------


def _register_single(reg: AgentRegistry, agent: AgentDefinition) -> None:
    agent_id = reg.register_agent(
        agent.header.agent_id, agent,
        ModelParameters(model_name="test/model", temperature=0.0),
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))


def test_pi_compile_writes_tool_scripts(tmp_target: Path) -> None:
    """extra_tools carrying tool_scripts get their files written to the
    pi tree — the body documents them as bash-invocable, so the scripts
    must exist."""
    from open_agent_compiler.model.core.permissions_model import JsonToolPermission
    from open_agent_compiler.model.core.tools_model import (
        ScriptDefinition,
        ToolDefinition,
        ToolDefinitionHeader,
        ToolDefinitionLogicJson,
        ToolScriptDefinition,
    )

    tool = ToolDefinition(
        header=ToolDefinitionHeader(
            name="notes_db", description="Notes DB.",
            usage_explanation_long="Store notes.",
            usage_explanation_short="notes", rules=[],
        ),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(tool_name="custom_tool", value="allow"),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
            tool_scripts=[
                ToolScriptDefinition(
                    paths=None,
                    scripts=[
                        ScriptDefinition(
                            target_file_path=Path("scripts/notes_db.py"),
                            source_file_path=None,
                            source_file_type="python",
                            script_contents="print('notes')\n",
                        )
                    ],
                )
            ],
        ),
    )
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="noter", name="noter", description="Notes."),
        usage_explanation_long="Takes notes.",
        usage_explanation_short="notes",
        system_prompt="You take notes.",
        extra_tools=[tool],
    )
    _register_single(reg, agent)

    build(tmp_target, reg, "prod", dialect="pi")
    script_path = tmp_target / "scripts" / "notes_db.py"
    assert script_path.exists()
    assert script_path.read_text() == "print('notes')\n"


def test_pi_compile_warns_on_mcp_servers(tmp_target: Path) -> None:
    """MCP servers can't be mapped to pi yet — the compiler must warn
    instead of silently stripping the capability."""
    from open_agent_compiler.model.core.agent_model import MCPServerDefinition

    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="mcpuser", name="mcpuser", description="Uses MCP."),
        usage_explanation_long="Talks to slack.",
        usage_explanation_short="mcp",
        system_prompt="You use slack.",
        mcp_servers=[MCPServerDefinition(name="slack")],
    )
    _register_single(reg, agent)

    with pytest.warns(UserWarning, match="MCP"):
        build(tmp_target, reg, "prod", dialect="pi")


def test_pi_step_criteria_rendered(tmp_target: Path) -> None:
    """Workflow step `evaluates` criteria are rendered so routes have a
    defined criteria_name to reference."""
    from open_agent_compiler.model.core.workflow_model import Criterion, Route

    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="router", name="router", description="Routes."),
        usage_explanation_long="Routes on quality.",
        usage_explanation_short="routes",
        system_prompt="You evaluate and route.",
        workflow=[
            WorkflowStepDefinition(
                id=1,
                name="Check",
                instructions="Assess the draft.",
                evaluates=(
                    Criterion(
                        name="quality",
                        question="Is the draft good enough to ship?",
                        possible_values=("yes", "no"),
                    ),
                ),
                routes=(
                    Route(criteria_name="quality", value="no", goto_step=1),
                ),
            ),
        ],
    )
    _register_single(reg, agent)

    build(tmp_target, reg, "prod", dialect="pi")
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    assert "Evaluate the following criteria" in content
    assert "**quality**: Is the draft good enough to ship?" in content
    assert "`yes` | `no`" in content


def test_pi_strict_todo_mode_emits_step0(tmp_target: Path) -> None:
    """strict todo_mode gets an explicit STEP 0 TODO.md bootstrap; lazy
    gets the lightweight note; the two must differ."""
    def _factory(mode: str) -> AgentRegistry:
        reg = AgentRegistry()
        agent = AgentDefinition(
            header=AgentHeader(agent_id="wf", name="wf", description="Works."),
            usage_explanation_long="Does steps.",
            usage_explanation_short="steps",
            system_prompt="You do steps.",
            todo_mode=mode,
            workflow=[
                WorkflowStepDefinition(id=1, name="Go", instructions="Do it."),
            ],
        )
        _register_single(reg, agent)
        return reg

    strict_dir = tmp_target / "strict"
    lazy_dir = tmp_target / "lazy"
    build(strict_dir, _factory("strict"), "prod", dialect="pi")
    build(lazy_dir, _factory("lazy"), "prod", dialect="pi")
    strict = (strict_dir / ".pi" / "agents" / "primary.md").read_text()
    lazy = (lazy_dir / ".pi" / "agents" / "primary.md").read_text()

    assert "STEP 0" in strict
    assert "TODO.md" in strict
    assert "STEP 0" not in lazy
    assert "Track your progress" in lazy


def test_pi_marks_done_suppressed_when_todo_mode_none(tmp_target: Path) -> None:
    """marks_done checklists are only rendered when the agent keeps a
    todo list at all."""
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="nt", name="nt", description="No todos."),
        usage_explanation_long="No todo tracking.",
        usage_explanation_short="nt",
        system_prompt="You work without todos.",
        todo_mode="none",
        workflow=[
            WorkflowStepDefinition(
                id=1, name="Go", instructions="Do it.",
                marks_done=("did-it",),
            ),
        ],
    )
    _register_single(reg, agent)

    build(tmp_target, reg, "prod", dialect="pi")
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    assert "did-it" not in content


def test_pi_primary_mode_subagents_use_agent_tool(tmp_target: Path) -> None:
    """Pi has exactly one spawn mechanism (Agent() from pi-subagents), so
    primary-mode subagents are listed there too — never as an unbacked
    'invoke via bash' instruction."""
    reg = AgentRegistry()
    sub = AgentDefinition(
        header=AgentHeader(agent_id="worker", name="worker", description="Works."),
        usage_explanation_long="Does work.",
        usage_explanation_short="works",
        system_prompt="You work.",
    )
    sub_id = reg.register_agent(
        "worker", sub, ModelParameters(model_name="test/model", temperature=0.0),
    )
    orch = AgentDefinition(
        header=AgentHeader(agent_id="boss", name="boss", description="Delegates."),
        usage_explanation_long="Delegates.",
        usage_explanation_short="boss",
        system_prompt="You delegate.",
        subagents=[
            AgentHeader(
                agent_id="worker", name="worker",
                description="Works.", mode="primary",
            )
        ],
        workflow=[
            WorkflowStepDefinition(
                id=1, name="Delegate", instructions="Hand off.",
                subagents=("worker",),
            ),
        ],
    )
    orch_id = reg.register_agent(
        "boss", orch, ModelParameters(model_name="test/model", temperature=0.0),
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[
                TemplateSlot(name="primary", default_agent_id=orch_id),
                TemplateSlot(name="worker", default_agent_id=sub_id),
            ],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))

    build(tmp_target, reg, "prod", dialect="pi")
    content = (tmp_target / ".pi" / "agents" / "primary.md").read_text()
    assert "Spawn subagents via Agent() tool" in content
    assert "Invoke agents via bash" not in content


def test_pi_usage_explanation_is_fallback_only(tmp_target: Path) -> None:
    """usage_explanation_long fills the body only when there is no
    system_prompt/workflow — otherwise it would duplicate content."""
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="dup", name="dup", description="Dup check."),
        usage_explanation_long="UNIQUE-USAGE-EXPLANATION-SENTINEL",
        usage_explanation_short="dup",
        system_prompt="You are the real prompt.",
    )
    _register_single(reg, agent)
    build(tmp_target / "with_prompt", reg, "prod", dialect="pi")
    content = (
        tmp_target / "with_prompt" / ".pi" / "agents" / "primary.md"
    ).read_text()
    assert "UNIQUE-USAGE-EXPLANATION-SENTINEL" not in content
    assert "You are the real prompt." in content

    reg2 = AgentRegistry()
    bare = AgentDefinition(
        header=AgentHeader(agent_id="bare", name="bare", description="Bare."),
        usage_explanation_long="UNIQUE-USAGE-EXPLANATION-SENTINEL",
        usage_explanation_short="bare",
    )
    _register_single(reg2, bare)
    build(tmp_target / "bare", reg2, "prod", dialect="pi")
    content2 = (tmp_target / "bare" / ".pi" / "agents" / "primary.md").read_text()
    assert "UNIQUE-USAGE-EXPLANATION-SENTINEL" in content2
