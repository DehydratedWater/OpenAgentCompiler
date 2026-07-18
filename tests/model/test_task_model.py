"""TaskHandle — long-running work contract."""

from __future__ import annotations


from open_agent_compiler.model.core.task_model import TaskHandle


def test_task_handle_defaults_to_pending() -> None:
    t = TaskHandle(run_id="r1")
    assert t.status == "pending"
    assert t.kind == "agent_run"
    assert t.is_terminal is False


def test_is_terminal_true_for_success_and_failure() -> None:
    assert TaskHandle(run_id="r", status="success").is_terminal is True
    assert TaskHandle(run_id="r", status="failure").is_terminal is True
    assert TaskHandle(run_id="r", status="running").is_terminal is False
    assert TaskHandle(run_id="r", status="timeout").is_terminal is False


def test_with_status_returns_new_handle() -> None:
    original = TaskHandle(run_id="r", status="pending")
    updated = original.with_status("running")
    assert original.status == "pending"
    assert updated.status == "running"


def test_with_status_can_set_result_atomically() -> None:
    t = TaskHandle(run_id="r", status="running").with_status(
        "success", result={"summary": "done"},
    )
    assert t.is_terminal
    assert t.result == {"summary": "done"}


def test_task_kind_spawn_distinct_from_agent_run() -> None:
    spawn = TaskHandle(run_id="s1", kind="spawned_agent")
    plain = TaskHandle(run_id="a1", kind="agent_run")
    assert spawn.kind != plain.kind


def test_eta_and_poll_url_are_optional() -> None:
    t = TaskHandle(run_id="r")
    assert t.eta_seconds is None
    assert t.poll_url is None
    t2 = TaskHandle(run_id="r", eta_seconds=120.0, poll_url="http://x/runs/r")
    assert t2.eta_seconds == 120.0
    assert t2.poll_url == "http://x/runs/r"
