"""End-to-end: compile a tiny tree and assert the right tool format is emitted."""

from __future__ import annotations

from pathlib import Path

import yaml

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
from open_agent_compiler.model.core.permissions_model import BashToolPermission, JsonToolPermission
from open_agent_compiler.model.core.skills_model import SkillDefinition, WorkflowStep
from open_agent_compiler.model.core.tools_model import (
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
    ToolDefinitionLogicJson,
)


def _dual_tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name=name, description=f"{name} description",
            usage_explanation_long="long", usage_explanation_short="short",
            rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=[f"uv run scripts/{name}.py *"],
            ),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
        ),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(tool_name="custom_tool", value="allow"),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
            tool_scripts=[],
        ),
    )


def _build_registry(agent_def: AgentDefinition) -> AgentRegistry:
    reg = AgentRegistry()
    agent_id = reg.register_agent(
        "demo", agent_def,
        ModelParameters(model_name="m", temperature=0.0),
    )
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


def _read_frontmatter(path: Path) -> dict:
    text = path.read_text()
    parts = text.split("---")
    return yaml.safe_load(parts[1])


def _agent_with_tool(tool: ToolDefinition, **kw) -> AgentDefinition:
    skill = SkillDefinition(
        name="demo-skill", description="demo",
        usage_explanation_long="l", usage_explanation_short="s",
        rules=[],
        workflow_steps=[
            WorkflowStep(
                header="step", condition=None, result=None, rule="do it",
                tools_used=[tool],
            )
        ],
        positive_examples=[], negative_examples=[],
    )
    return AgentDefinition(
        header=AgentHeader(agent_id="a", name="a", description="a"),
        usage_explanation_long="l", usage_explanation_short="s",
        skills=[skill],
        **kw,
    )


def test_bash_default_emits_only_bash_allowlist(tmp_target: Path) -> None:
    tool = _dual_tool("widget")
    agent = _agent_with_tool(tool)  # default_tool_format="bash"
    reg = _build_registry(agent)
    CompileScript(target=tmp_target, factory=lambda: reg, config="prod").run()

    fm = _read_frontmatter(tmp_target / ".opencode" / "agents" / "primary.md")
    assert "bash" in fm["permission"]
    assert "uv run scripts/widget.py *" in fm["permission"]["bash"]
    assert "widget" not in fm["permission"]
    assert "custom_tools" not in fm


def test_json_default_emits_custom_tool_block(tmp_target: Path) -> None:
    tool = _dual_tool("widget")
    agent = _agent_with_tool(tool, default_tool_format="json")
    reg = _build_registry(agent)
    CompileScript(target=tmp_target, factory=lambda: reg, config="prod").run()

    fm = _read_frontmatter(tmp_target / ".opencode" / "agents" / "primary.md")
    # Bash should NOT be in the permission block.
    assert "bash" not in fm["permission"]
    # The tool-name should be present as a custom_tool permission.
    assert fm["permission"]["widget"] == "allow"
    # And a structured tool block should exist.
    names = [b["name"] for b in fm["custom_tools"]]
    assert names == ["widget"]


def test_both_emits_bash_and_custom_tool(tmp_target: Path) -> None:
    tool = _dual_tool("widget")
    agent = _agent_with_tool(tool, default_tool_format="both")
    reg = _build_registry(agent)
    CompileScript(target=tmp_target, factory=lambda: reg, config="prod").run()

    fm = _read_frontmatter(tmp_target / ".opencode" / "agents" / "primary.md")
    assert "uv run scripts/widget.py *" in fm["permission"]["bash"]
    assert fm["permission"]["widget"] == "allow"
    assert any(b["name"] == "widget" for b in fm["custom_tools"])


def test_per_tool_override_picks_json_for_one_tool_only(tmp_target: Path) -> None:
    t1 = _dual_tool("alpha")
    t2 = _dual_tool("beta")
    # Both tools live on one skill.
    skill = SkillDefinition(
        name="s", description="", usage_explanation_long="l",
        usage_explanation_short="s", rules=[],
        workflow_steps=[
            WorkflowStep(
                header="step", condition=None, result=None, rule="r",
                tools_used=[t1, t2],
            ),
        ],
        positive_examples=[], negative_examples=[],
    )
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="a", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        skills=[skill],
        default_tool_format="bash",
        tool_format_overrides={"beta": "json"},
    )
    reg = _build_registry(agent)
    CompileScript(target=tmp_target, factory=lambda: reg, config="prod").run()

    fm = _read_frontmatter(tmp_target / ".opencode" / "agents" / "primary.md")
    assert "uv run scripts/alpha.py *" in fm["permission"]["bash"]
    assert "uv run scripts/beta.py *" not in fm["permission"].get("bash", {})
    assert fm["permission"]["beta"] == "allow"
    assert "alpha" not in fm["permission"]
