"""SpawnAgentTool — spawn an opencode agent and return a TaskHandle."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch


from open_agent_compiler.runtime_spawn import (
    SpawnAgentInput,
    SpawnAgentOutput,
    SpawnAgentTool,
)


def _setup_manager_in(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    manager = scripts / "opencode_manager.py"
    manager.write_text("# stub for spawn tests\n")
    return manager


def test_input_output_schemas_resolve_via_generic_param() -> None:
    assert SpawnAgentTool._get_input_type() is SpawnAgentInput
    assert SpawnAgentTool._get_output_type() is SpawnAgentOutput


def test_returns_failure_when_manager_not_found(monkeypatch, tmp_path: Path) -> None:
    """No scripts/opencode_manager.py anywhere upward → failure handle."""
    monkeypatch.chdir(tmp_path)
    tool = SpawnAgentTool()
    out = tool.execute(SpawnAgentInput(agent_name="x", prompt="hi"))
    assert isinstance(out, SpawnAgentOutput)
    assert out.task.status == "failure"
    assert "not found" in (out.task.error_message or "")


def test_blocking_spawn_returns_success_handle_on_zero_returncode(
    monkeypatch, tmp_path: Path,
) -> None:
    """A normal blocking spawn returns status=success with stdout captured."""
    _setup_manager_in(tmp_path)
    monkeypatch.chdir(tmp_path)
    fake_completed = MagicMock(returncode=0, stdout="hello", stderr="")
    with patch("subprocess.run", return_value=fake_completed) as mock_run:
        out = SpawnAgentTool().execute(
            SpawnAgentInput(agent_name="x", prompt="say hi"),
        )
    assert out.task.status == "success"
    assert out.stdout == "hello"
    assert out.task.kind == "spawned_agent"
    # Built the expected `uv run scripts/opencode_manager.py run --agent x say hi`.
    cmd = mock_run.call_args[0][0]
    assert "uv" in cmd[0]
    assert "--agent" in cmd
    assert "x" in cmd
    assert "say hi" in cmd


def test_blocking_spawn_returns_failure_on_nonzero_returncode(
    monkeypatch, tmp_path: Path,
) -> None:
    _setup_manager_in(tmp_path)
    monkeypatch.chdir(tmp_path)
    fake_completed = MagicMock(returncode=2, stdout="", stderr="oops")
    with patch("subprocess.run", return_value=fake_completed):
        out = SpawnAgentTool().execute(
            SpawnAgentInput(agent_name="x", prompt="p"),
        )
    assert out.task.status == "failure"
    assert out.task.error_message == "oops"


def test_blocking_spawn_returns_timeout_handle(
    monkeypatch, tmp_path: Path,
) -> None:
    _setup_manager_in(tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["x"], timeout=1.0),
    ):
        out = SpawnAgentTool().execute(
            SpawnAgentInput(agent_name="x", prompt="p", timeout_s=1.0),
        )
    assert out.task.status == "timeout"


def test_async_spawn_returns_running_handle_with_poll_url(
    monkeypatch, tmp_path: Path,
) -> None:
    """spawn_async=True → status=running, poll_url set, no blocking."""
    _setup_manager_in(tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch("subprocess.Popen") as mock_popen:
        out = SpawnAgentTool().execute(
            SpawnAgentInput(agent_name="x", prompt="p", spawn_async=True),
        )
    assert out.task.status == "running"
    assert out.task.poll_url is not None
    assert out.task.run_id in out.task.poll_url
    mock_popen.assert_called_once()


def test_context_dict_surfaces_as_oac_ctx_env_vars(
    monkeypatch, tmp_path: Path,
) -> None:
    _setup_manager_in(tmp_path)
    monkeypatch.chdir(tmp_path)
    fake_completed = MagicMock(returncode=0, stdout="", stderr="")
    with patch("subprocess.run", return_value=fake_completed) as mock_run:
        SpawnAgentTool().execute(SpawnAgentInput(
            agent_name="x", prompt="p",
            context={"user_id": "alice", "session": "s1"},
        ))
    env = mock_run.call_args.kwargs["env"]
    assert env["OAC_CTX_USER_ID"] == "alice"
    assert env["OAC_CTX_SESSION"] == "s1"
