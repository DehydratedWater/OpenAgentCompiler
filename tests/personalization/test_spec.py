"""ClientSpec / ExampleTask validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from open_agent_compiler.personalization import ClientSpec, ExampleTask


def test_example_task_requires_non_empty_prompt() -> None:
    ExampleTask(prompt="do a thing")  # ok
    with pytest.raises(ValidationError):
        ExampleTask(prompt="   ")


def test_client_spec_requires_non_empty_goal() -> None:
    with pytest.raises(ValidationError):
        ClientSpec(goal="  ")


def test_client_spec_is_frozen() -> None:
    spec = ClientSpec(goal="g", example_tasks=(ExampleTask(prompt="t"),))
    with pytest.raises(ValidationError):
        spec.goal = "other"  # type: ignore[misc]


def test_spec_without_example_tasks_exists_but_not_usable() -> None:
    spec = ClientSpec(goal="g")
    assert spec.is_usable is False
    with pytest.raises(ValueError, match="no example_tasks"):
        spec.require_usable()


def test_require_usable_needs_success_criteria_too() -> None:
    spec = ClientSpec(goal="g", example_tasks=(ExampleTask(prompt="t"),))
    assert spec.is_usable is True  # has an example task
    with pytest.raises(ValueError, match="no success_criteria"):
        spec.require_usable()


def test_require_usable_passes_for_full_spec(valid_spec: ClientSpec) -> None:
    assert valid_spec.require_usable() is valid_spec
