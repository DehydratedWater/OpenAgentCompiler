"""Scenario data model for agent integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCommand:
    """A single tool script invocation."""

    script: str  # e.g. "scripts/goal_manager.py"
    # CLI args: {"command": "create", ...}
    args: dict[str, str] = field(default_factory=dict)


@dataclass
class LLMCriterion:
    """Criteria for LLM judge evaluation."""

    description: str  # What to evaluate
    passing_threshold: float = 0.7  # 0-1 confidence threshold


@dataclass
class Assertion:
    """Programmatic assertion on tool output."""

    field: str  # JSON path in output, e.g. "success", "goals[0].title"
    operator: str  # "eq", "contains", "gt", "lt", "truthy", "length_gte"
    expected: Any  # Expected value


@dataclass
class VerifyStep:
    """Run a tool command, then check assertions/LLM eval."""

    command: ToolCommand
    assertions: list[Assertion] = field(default_factory=list)
    llm_criteria: list[LLMCriterion] = field(default_factory=list)


@dataclass
class Scenario:
    """Complete test scenario for one agent."""

    name: str  # Human-readable scenario name
    agent: str  # Agent path, e.g. "goals/twily_goal_interface"
    description: str  # What this scenario tests
    seed_commands: list[ToolCommand]  # Seed data setup (run before agent)
    agent_prompt: str  # Input prompt to the agent
    verify_steps: list[VerifyStep]  # Post-execution verification
    # Evaluate full flow log
    flow_llm_criteria: list[LLMCriterion] = field(
        default_factory=list,
    )
    timeout: int = 300  # Agent execution timeout (seconds)
