"""Test definition models — AgentTest, ToolTest, CapabilityTest, evaluators."""

from __future__ import annotations

from open_agent_compiler.model.core.test_model import (
    AgentTest,
    CapabilityTest,
    EqualsEvaluator,
    JsonPathEvaluator,
    LLMJudgeEvaluator,
    PermissionPresentEvaluator,
    RegexEvaluator,
    SubstringEvaluator,
    ToolCalledEvaluator,
    ToolNotCalledEvaluator,
    ToolTest,
)


def test_capability_test_minimal_fields() -> None:
    t = CapabilityTest(name="permits-bash")
    assert t.must_have_tools == ()
    assert t.must_not_have_skills == ()
    assert t.evaluators == ()


def test_capability_test_must_have_must_not_have_lists() -> None:
    t = CapabilityTest(
        name="t",
        must_have_tools=("read", "bash"),
        must_not_have_tools=("write",),
        must_have_skills=("data-query",),
        must_have_bash_patterns=("uv run scripts/safe.py *",),
    )
    assert t.must_have_tools == ("read", "bash")
    assert t.must_not_have_tools == ("write",)


def test_tool_test_round_trip() -> None:
    t = ToolTest(
        name="happy-path",
        input={"x": 1, "y": "two"},
        mock_profile="ci",
        access_profile="test-A",
        evaluators=(EqualsEvaluator(expected={"ok": True}),),
    )
    assert t.input == {"x": 1, "y": "two"}
    assert t.mock_profile == "ci"


def test_agent_test_expected_tool_calls_shorthand() -> None:
    t = AgentTest(
        name="triage-routes-to-escalator",
        prompt="urgent: server down",
        expected_tool_calls=("triage-tool", "escalator"),
    )
    assert t.expected_tool_calls == ("triage-tool", "escalator")


def test_each_evaluator_kind_is_discriminated() -> None:
    evals = [
        EqualsEvaluator(expected=1),
        SubstringEvaluator(needle="hi"),
        RegexEvaluator(pattern=r"\d+"),
        JsonPathEvaluator(path="tasks.0.id", expected="abc"),
        ToolCalledEvaluator(tool_name="t", with_args_subset={"k": "v"}),
        ToolNotCalledEvaluator(tool_name="dangerous"),
        PermissionPresentEvaluator(permission_key="read"),
        LLMJudgeEvaluator(criteria="answers the question"),
    ]
    kinds = {e.kind for e in evals}
    assert "equals" in kinds and "tool_called" in kinds and "llm_judge" in kinds
    # And every kind value is unique
    assert len(kinds) == len(evals)


def test_agent_definition_accepts_embedded_tests() -> None:
    from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader

    a = AgentDefinition(
        header=AgentHeader(agent_id="x", name="x", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        agent_tests=[
            AgentTest(name="happy", prompt="hi"),
        ],
        capability_tests=[
            CapabilityTest(name="read-allowed", must_have_tools=("read",)),
        ],
    )
    assert len(a.agent_tests) == 1
    assert len(a.capability_tests) == 1


def test_tool_definition_accepts_embedded_tool_tests() -> None:
    from open_agent_compiler.model.core.permissions_model import BashToolPermission
    from open_agent_compiler.model.core.tools_model import (
        ToolDefinition,
        ToolDefinitionHeader,
        ToolDefinitionLogicBash,
    )

    t = ToolDefinition(
        header=ToolDefinitionHeader(
            name="echo", description="echoes",
            usage_explanation_long="l", usage_explanation_short="s",
            rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(tool_name="bash", value="allow"),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
        ),
        tool_tests=[ToolTest(name="happy", input={"x": 1})],
    )
    assert t.tool_tests[0].name == "happy"


# ---- Phase 11: Multi-turn AgentTest + Turn -----------------------------


def test_agent_test_single_turn_backwards_compatible() -> None:
    """The pre-Phase-11 shape (top-level prompt) still works."""
    t = AgentTest(name="t", prompt="hello")
    assert t.is_multi_turn is False
    turns = t.all_turns()
    assert len(turns) == 1
    assert turns[0].prompt == "hello"


def test_agent_test_accepts_multi_turn() -> None:
    from open_agent_compiler.model.core.test_model import Turn
    t = AgentTest(
        name="multi",
        turns=(
            Turn(prompt="first message"),
            Turn(prompt="follow-up"),
            Turn(prompt="last one"),
        ),
    )
    assert t.is_multi_turn is True
    assert len(t.all_turns()) == 3
    assert t.all_turns()[1].prompt == "follow-up"


def test_agent_test_rejects_both_prompt_and_turns() -> None:
    import pytest
    from open_agent_compiler.model.core.test_model import Turn
    with pytest.raises(ValueError, match="cannot set both"):
        AgentTest(name="x", prompt="hi", turns=(Turn(prompt="bad"),))


def test_agent_test_rejects_neither_prompt_nor_turns() -> None:
    import pytest
    with pytest.raises(ValueError, match="must set either"):
        AgentTest(name="x")


def test_turn_carries_per_turn_evaluators_and_expected_tool_calls() -> None:
    from open_agent_compiler.model.core.test_model import Turn
    turn = Turn(
        prompt="check stock",
        expected_tool_calls=("stock_lookup",),
        evaluators=(SubstringEvaluator(needle="in stock"),),
    )
    assert turn.expected_tool_calls == ("stock_lookup",)
    assert turn.evaluators[0].needle == "in stock"


def test_agent_test_single_turn_all_turns_includes_top_level_evaluators() -> None:
    """all_turns() forwards top-level evaluators + expected_tool_calls into
    the synthesized single Turn so the runner sees them uniformly."""
    t = AgentTest(
        name="t", prompt="hi",
        expected_tool_calls=("foo",),
        evaluators=(SubstringEvaluator(needle="hi"),),
    )
    turn = t.all_turns()[0]
    assert turn.expected_tool_calls == ("foo",)
    assert turn.evaluators[0].needle == "hi"
