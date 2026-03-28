"""Tests for the testing scenario data model and assertion logic."""

from open_agent_compiler.testing.runner import (
    AgentRunResult,
    ScenarioResult,
    _check_assertion,
    _resolve_field,
)
from open_agent_compiler.testing.scenario import (
    Assertion,
    LLMCriterion,
    Scenario,
    ToolCommand,
    VerifyStep,
)


class TestToolCommand:
    def test_basic_construction(self):
        cmd = ToolCommand("scripts/foo.py", {"command": "create", "name": "bar"})
        assert cmd.script == "scripts/foo.py"
        assert cmd.args == {"command": "create", "name": "bar"}

    def test_default_args(self):
        cmd = ToolCommand("scripts/foo.py")
        assert cmd.args == {}


class TestLLMCriterion:
    def test_default_threshold(self):
        c = LLMCriterion("Agent should greet user")
        assert c.passing_threshold == 0.7

    def test_custom_threshold(self):
        c = LLMCriterion("Strict check", passing_threshold=0.9)
        assert c.passing_threshold == 0.9


class TestAssertion:
    def test_construction(self):
        a = Assertion("success", "eq", True)
        assert a.field == "success"
        assert a.operator == "eq"
        assert a.expected is True


class TestVerifyStep:
    def test_defaults(self):
        step = VerifyStep(command=ToolCommand("scripts/x.py"))
        assert step.assertions == []
        assert step.llm_criteria == []

    def test_with_assertions(self):
        step = VerifyStep(
            command=ToolCommand("scripts/x.py"),
            assertions=[Assertion("success", "eq", True)],
            llm_criteria=[LLMCriterion("Should work")],
        )
        assert len(step.assertions) == 1
        assert len(step.llm_criteria) == 1


class TestScenario:
    def test_full_construction(self):
        s = Scenario(
            name="Test scenario",
            agent="goals/test_agent",
            description="Tests something",
            seed_commands=[ToolCommand("scripts/seed.py", {"command": "create"})],
            agent_prompt="Do something",
            verify_steps=[
                VerifyStep(
                    command=ToolCommand("scripts/verify.py", {"command": "list"}),
                    assertions=[Assertion("success", "eq", True)],
                ),
            ],
        )
        assert s.name == "Test scenario"
        assert s.timeout == 1800
        assert s.flow_llm_criteria == []

    def test_custom_timeout(self):
        s = Scenario(
            name="Slow test",
            agent="x/y",
            description="d",
            seed_commands=[],
            agent_prompt="p",
            verify_steps=[],
            timeout=600,
        )
        assert s.timeout == 600


class TestResolveField:
    def test_simple_key(self):
        assert _resolve_field({"success": True}, "success") is True

    def test_nested_key(self):
        data = {"result": {"count": 5}}
        assert _resolve_field(data, "result.count") == 5

    def test_array_index(self):
        data = {"items": ["a", "b", "c"]}
        assert _resolve_field(data, "items[1]") == "b"

    def test_nested_array(self):
        data = {"goals": [{"title": "First"}, {"title": "Second"}]}
        assert _resolve_field(data, "goals[0].title") == "First"
        assert _resolve_field(data, "goals[1].title") == "Second"


class TestCheckAssertion:
    def test_eq_pass(self):
        result = _check_assertion({"success": True}, Assertion("success", "eq", True))
        assert result.passed is True

    def test_eq_fail(self):
        result = _check_assertion({"success": False}, Assertion("success", "eq", True))
        assert result.passed is False

    def test_contains(self):
        result = _check_assertion(
            {"msg": "hello world"},
            Assertion("msg", "contains", "world"),
        )
        assert result.passed is True

    def test_gt(self):
        result = _check_assertion({"count": 5}, Assertion("count", "gt", 3))
        assert result.passed is True

    def test_lt(self):
        result = _check_assertion({"count": 2}, Assertion("count", "lt", 3))
        assert result.passed is True

    def test_truthy(self):
        result = _check_assertion({"items": [1, 2]}, Assertion("items", "truthy", None))
        assert result.passed is True

    def test_length_gte(self):
        result = _check_assertion(
            {"items": [1, 2, 3]},
            Assertion("items", "length_gte", 2),
        )
        assert result.passed is True

    def test_missing_field(self):
        result = _check_assertion({}, Assertion("missing", "eq", True))
        assert result.passed is False
        assert "not found" in result.message

    def test_unknown_operator(self):
        result = _check_assertion({"x": 1}, Assertion("x", "bogus", 1))
        assert result.passed is False
        assert "Unknown operator" in result.message


class TestAgentRunResult:
    def test_default_duration(self):
        r = AgentRunResult(return_code=0, stdout="", stderr="", flow_log="")
        assert r.duration_seconds == 0.0

    def test_custom_duration(self):
        r = AgentRunResult(
            return_code=0, stdout="", stderr="", flow_log="", duration_seconds=12.5
        )
        assert r.duration_seconds == 12.5

    def test_subagent_fallback_not_detected(self):
        r = AgentRunResult(
            return_code=0, stdout="", stderr="", flow_log="Agent ran normally"
        )
        assert r.subagent_fallback is False

    def test_subagent_fallback_detected(self):
        r = AgentRunResult(
            return_code=0,
            stdout="",
            stderr="",
            flow_log=(
                'agent "goals/my-test-agent" not found. Falling back to default agent'
            ),
        )
        assert r.subagent_fallback is True

    def test_subagent_fallback_falling_back(self):
        r = AgentRunResult(
            return_code=0,
            stdout="",
            stderr="",
            flow_log='agent "workflows/server" not found. Falling back to default',
        )
        assert r.subagent_fallback is True


class TestScenarioResult:
    def _make_scenario(self):
        return Scenario(
            name="Test",
            agent="x/y",
            description="d",
            seed_commands=[],
            agent_prompt="p",
            verify_steps=[],
        )

    def test_default_duration(self):
        r = ScenarioResult(
            scenario=self._make_scenario(),
            seed_outputs=[],
            agent_result=AgentRunResult(
                return_code=0, stdout="", stderr="", flow_log=""
            ),
            verify_results=[],
        )
        assert r.duration_seconds == 0.0

    def test_custom_duration(self):
        r = ScenarioResult(
            scenario=self._make_scenario(),
            seed_outputs=[],
            agent_result=AgentRunResult(
                return_code=0, stdout="", stderr="", flow_log=""
            ),
            verify_results=[],
            duration_seconds=45.2,
        )
        assert r.duration_seconds == 45.2

    def test_summary_includes_duration(self):
        r = ScenarioResult(
            scenario=self._make_scenario(),
            seed_outputs=[{"success": True}],
            agent_result=AgentRunResult(
                return_code=0,
                stdout="",
                stderr="",
                flow_log="",
                duration_seconds=5.3,
            ),
            verify_results=[],
            duration_seconds=10.7,
        )
        text = r.summary()
        assert "10.7s" in text
        assert "5.3s" in text
        assert "1 ok, 0 failed" in text

    def test_subagent_fallback_fails_scenario(self):
        r = ScenarioResult(
            scenario=self._make_scenario(),
            seed_outputs=[],
            agent_result=AgentRunResult(
                return_code=0,
                stdout="",
                stderr="",
                flow_log=(
                    'agent "goals/my-test-agent"'
                    " not found. Falling back to default agent"
                ),
            ),
            verify_results=[],
        )
        assert r.all_passed is False
        text = r.summary()
        assert "[FATAL] Subagent fallback" in text

    def test_summary_shows_flow_log_on_failure(self):
        r = ScenarioResult(
            scenario=self._make_scenario(),
            seed_outputs=[],
            agent_result=AgentRunResult(
                return_code=1,
                stdout="",
                stderr="some error",
                flow_log="debug output here",
            ),
            verify_results=[],
        )
        text = r.summary()
        assert "Flow log excerpt" in text
        assert "debug output here" in text
