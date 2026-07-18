"""Bundled opencode_manager.py — status/logs paths + CLI plumbing.

End-to-end server start/run tests would need a real `opencode` binary,
so we focus on the parts that are deterministic without it: status when
no PID file exists, log discovery, the subagent-detection helper,
and CLI dispatch into stub handlers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.scripts import opencode_manager as ocm


def test_status_no_pid_file_reports_stopped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ocm, "PID_FILE", tmp_path / "no-pid")
    status = ocm.OpenCodeManager.get_status()
    assert status["running"] is False
    assert status["pid"] is None
    assert status["url"] is None
    assert status["port"] == ocm.OPENCODE_PORT


def test_is_server_running_false_without_pid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ocm, "PID_FILE", tmp_path / "absent")
    assert ocm.OpenCodeManager.is_server_running() is False


def test_is_server_running_clears_stale_pid_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pid_file = tmp_path / "stale.pid"
    pid_file.write_text("999999999")  # almost certainly nonexistent
    monkeypatch.setattr(ocm, "PID_FILE", pid_file)
    assert ocm.OpenCodeManager.is_server_running() is False
    assert not pid_file.exists()  # cleaned up


def test_agent_is_subagent_reads_yaml_frontmatter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    proj = tmp_path / "proj"
    agents_dir = proj / ".opencode" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "persona").mkdir()
    sub_md = agents_dir / "persona" / "quick.md"
    sub_md.write_text("---\ndescription: q\nmode: subagent\n---\n# body\n")
    monkeypatch.setattr(ocm, "PROJECT_ROOT", proj)
    assert ocm.OpenCodeManager._agent_is_subagent("persona/quick") is True

    pri_md = agents_dir / "persona" / "primary.md"
    pri_md.write_text("---\nmode: primary\n---\n")
    assert ocm.OpenCodeManager._agent_is_subagent("persona/primary") is False

    assert ocm.OpenCodeManager._agent_is_subagent("ghost/never-existed") is False


def test_get_recent_logs_returns_empty_when_no_logs_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(ocm, "LOGS_DIR", tmp_path / "no-logs")
    assert ocm.OpenCodeManager.get_recent_logs() == []


def test_get_recent_logs_returns_sorted_by_mtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import os
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(ocm, "LOGS_DIR", logs_dir)
    a = logs_dir / "a.log"; a.write_text("a")
    b = logs_dir / "b.log"; b.write_text("b")
    # Make a older
    os.utime(a, (1, 1))
    out = ocm.OpenCodeManager.get_recent_logs(limit=10)
    names = [e["filename"] for e in out]
    assert names == ["b.log", "a.log"]


def test_save_log_writes_structured_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(ocm, "LOGS_DIR", tmp_path / "logs")
    from datetime import datetime
    start = datetime(2026, 5, 17, 12, 0, 0)
    end = datetime(2026, 5, 17, 12, 0, 5)
    path = ocm.OpenCodeManager._save_log(
        prefix="pfx", agent="goals/orch", prompt="hello",
        stdout=b"hi", stderr=b"", return_code=0,
        start_time=start, end_time=end,
    )
    assert path is not None
    body = path.read_text()
    assert "Agent: goals/orch" in body
    assert "Duration: 5.0s" in body
    assert "hello" in body
    assert "hi" in body


# ---- CLI plumbing --------------------------------------------------------


def test_cli_server_status_returns_zero(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(ocm, "PID_FILE", tmp_path / "no-pid")
    rc = ocm.main(["server", "status"])
    assert rc == 0
    assert "STOPPED" in capsys.readouterr().out


def test_cli_logs_when_no_logs(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(ocm, "LOGS_DIR", tmp_path / "no-logs")
    rc = ocm.main(["logs"])
    assert rc == 0
    assert "No logs found" in capsys.readouterr().out


def test_cli_no_command_prints_help_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ocm.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "server" in out and "run" in out


def test_cli_run_without_prompt_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ocm.main(["run", "--agent", "x"])
    assert rc == 1
    assert "prompt is required" in capsys.readouterr().out


def test_create_opencode_manager_tool_points_to_new_script_path() -> None:
    """The tool spec's script path must match the new bundled location."""
    from open_agent_compiler.model.core.core_tools_model import create_opencode_manager_tool
    tool = create_opencode_manager_tool()
    # The script bundle path is wired into both bash examples and json_tool.
    found_in_examples = any(
        "scripts/opencode_manager.py" in ex
        for ex in tool.bash_tool.positive_examples
    )
    assert found_in_examples
    # And no longer references the old scripts/core path.
    for ex in tool.bash_tool.positive_examples:
        assert "scripts/core/opencode_manager.py" not in ex
