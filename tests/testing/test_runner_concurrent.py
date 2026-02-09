"""Tests for ScenarioRunner.run_scenarios (sequential and concurrent)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from open_agent_compiler.testing.runner import (
    AgentRunResult,
    ScenarioResult,
    ScenarioRunner,
)
from open_agent_compiler.testing.scenario import Scenario


def _make_scenario(name: str) -> Scenario:
    return Scenario(
        name=name,
        agent="test/agent",
        description=f"Scenario {name}",
        seed_commands=[],
        agent_prompt=f"Do {name}",
        verify_steps=[],
    )


def _make_scenario_result(scenario: Scenario) -> ScenarioResult:
    return ScenarioResult(
        scenario=scenario,
        seed_outputs=[],
        agent_result=AgentRunResult(
            return_code=0,
            stdout="",
            stderr="",
            flow_log="ok",
        ),
        verify_results=[],
    )


@pytest.fixture
def mock_runner():
    """Build a ScenarioRunner with fully mocked dependencies."""
    tool_runner = MagicMock()
    tool_runner.run_sequence.return_value = []
    tool_runner.env = {}

    judge = MagicMock()
    judge.evaluate_flow = AsyncMock(return_value=[])

    runner = ScenarioRunner(
        tool_runner=tool_runner,
        judge=judge,
        project_root=MagicMock(),
    )
    return runner


class TestRunScenarios:
    @pytest.mark.asyncio
    async def test_sequential_returns_all_results(self, mock_runner: ScenarioRunner):
        scenarios = [_make_scenario("A"), _make_scenario("B"), _make_scenario("C")]

        # Patch run_scenario to return mock results
        results_map = {s.name: _make_scenario_result(s) for s in scenarios}
        mock_runner.run_scenario = AsyncMock(side_effect=lambda s: results_map[s.name])

        results = await mock_runner.run_scenarios(scenarios, concurrent=False)
        assert len(results) == 3
        assert [r.scenario.name for r in results] == ["A", "B", "C"]

    @pytest.mark.asyncio
    async def test_concurrent_returns_all_results(self, mock_runner: ScenarioRunner):
        scenarios = [_make_scenario("A"), _make_scenario("B"), _make_scenario("C")]

        results_map = {s.name: _make_scenario_result(s) for s in scenarios}
        mock_runner.run_scenario = AsyncMock(side_effect=lambda s: results_map[s.name])

        results = await mock_runner.run_scenarios(scenarios, concurrent=True)
        assert len(results) == 3
        # All scenarios should have been called
        assert mock_runner.run_scenario.call_count == 3

    @pytest.mark.asyncio
    async def test_empty_scenarios(self, mock_runner: ScenarioRunner):
        results = await mock_runner.run_scenarios([], concurrent=False)
        assert results == []

        results = await mock_runner.run_scenarios([], concurrent=True)
        assert results == []

    @pytest.mark.asyncio
    async def test_sequential_preserves_order(self, mock_runner: ScenarioRunner):
        """Sequential mode must preserve scenario order."""
        call_order: list[str] = []
        scenarios = [_make_scenario(n) for n in ("first", "second", "third")]

        async def track_order(s: Scenario) -> ScenarioResult:
            call_order.append(s.name)
            return _make_scenario_result(s)

        mock_runner.run_scenario = AsyncMock(side_effect=track_order)

        await mock_runner.run_scenarios(scenarios, concurrent=False)
        assert call_order == ["first", "second", "third"]
