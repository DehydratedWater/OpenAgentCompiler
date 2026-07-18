"""Shared pytest fixtures.

Layout convention: tests/ mirrors open_agent_compiler/. A fixture defined here is visible to
every test; fixtures specific to a subtree go in that subtree's conftest.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    ModelParameters,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry


@pytest.fixture()
def tmp_target(tmp_path: Path) -> Path:
    """A temporary directory to write compiled artifacts into."""
    out = tmp_path / "build"
    out.mkdir()
    return out


@pytest.fixture()
def minimal_agent() -> AgentDefinition:
    """The smallest valid AgentDefinition — a primary with no skills/subagents."""
    return AgentDefinition(
        header=AgentHeader(
            agent_id="placeholder",
            name="minimal",
            description="A minimal agent for tests.",
        ),
        usage_explanation_long="Used by tests as a trivial baseline.",
        usage_explanation_short="trivial baseline",
    )


@pytest.fixture()
def fast_model() -> ModelParameters:
    return ModelParameters(model_name="test-model-fast", temperature=0.0)


@pytest.fixture()
def slow_model() -> ModelParameters:
    return ModelParameters(model_name="test-model-slow", temperature=0.7)


@pytest.fixture()
def registry(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
) -> AgentRegistry:
    """A registry with one agent pre-registered as `minimal_test-model-fast_t0.0`."""
    reg = AgentRegistry()
    reg.register_agent("minimal", minimal_agent, fast_model)
    return reg
