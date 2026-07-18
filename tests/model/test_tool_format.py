"""AgentDefinition.chosen_format — picks bash/json/both per tool."""

from __future__ import annotations


from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader
from open_agent_compiler.model.core.permissions_model import BashToolPermission, JsonToolPermission
from open_agent_compiler.model.core.tools_model import (
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
    ToolDefinitionLogicJson,
)


def _make_tool(name: str, *, bash: bool = True, json: bool = True) -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name=name, description=name, usage_explanation_long="l",
            usage_explanation_short="s", rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(tool_name="bash", value="allow"),
            positive_examples=[f"uv run {name}.py --x 1"],
            negative_examples=[], mode_specific_rules=[],
        ) if bash else None,
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(tool_name="custom_tool", value="allow"),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
            tool_scripts=[],
        ) if json else None,
    )


def _agent(**kw) -> AgentDefinition:
    base = dict(
        header=AgentHeader(agent_id="a", name="a", description=None),
        usage_explanation_long="l",
        usage_explanation_short="s",
    )
    base.update(kw)
    return AgentDefinition(**base)


def test_default_format_is_bash_when_both_available() -> None:
    a = _agent()
    assert a.chosen_format(_make_tool("t")) == "bash"


def test_agent_default_json_picks_json() -> None:
    a = _agent(default_tool_format="json")
    assert a.chosen_format(_make_tool("t")) == "json"


def test_agent_default_both_picks_both_when_tool_has_both() -> None:
    a = _agent(default_tool_format="both")
    assert a.chosen_format(_make_tool("t")) == "both"


def test_agent_default_both_falls_back_to_whichever_tool_offers() -> None:
    a = _agent(default_tool_format="both")
    assert a.chosen_format(_make_tool("t", json=False)) == "bash"
    assert a.chosen_format(_make_tool("t", bash=False)) == "json"


def test_per_tool_override_beats_agent_default() -> None:
    a = _agent(
        default_tool_format="bash",
        tool_format_overrides={"special": "json"},
    )
    assert a.chosen_format(_make_tool("special")) == "json"
    assert a.chosen_format(_make_tool("ordinary")) == "bash"


def test_json_preference_falls_back_to_bash_when_tool_has_no_json() -> None:
    a = _agent(default_tool_format="json")
    assert a.chosen_format(_make_tool("t", json=False)) == "bash"


def test_bash_preference_falls_back_to_json_when_tool_has_no_bash() -> None:
    a = _agent(default_tool_format="bash")
    assert a.chosen_format(_make_tool("t", bash=False)) == "json"
