"""Bundled subagent_todo.py — file-based todo for subagents."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from open_agent_compiler.scripts import subagent_todo as sat


@pytest.fixture(autouse=True)
def isolated_todos_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OAC_TODOS_DIR", str(tmp_path / "todos"))
    return tmp_path / "todos"


def test_init_creates_file_with_zero_tasks(isolated_todos_dir: Path) -> None:
    out = sat.init_todo_list("persona/orch", run_id="r1")
    assert out["success"]
    path = Path(out["path"])
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["agent_name"] == "persona/orch"
    assert data["run_id"] == "r1"
    assert data["tasks"] == []


def test_filename_sanitizes_slashes_and_spaces(isolated_todos_dir: Path) -> None:
    sat.init_todo_list("persona/quick ack", run_id="r1")
    files = list(isolated_todos_dir.glob("*.json"))
    assert len(files) == 1
    assert "persona_quick_ack" in files[0].name


def test_add_then_list_returns_task() -> None:
    sat.init_todo_list("a", run_id="r1")
    add = sat.add_task("a", "r1", subject="step one", description="do it")
    assert add["success"]
    listing = sat.list_tasks("a", "r1")
    assert listing["task_count"] == 1
    assert listing["tasks"][0]["subject"] == "step one"
    assert listing["tasks"][0]["status"] == "pending"


def test_get_returns_specific_task_or_error() -> None:
    sat.init_todo_list("a", run_id="r1")
    tid = sat.add_task("a", "r1", subject="x")["task"]["id"]
    assert sat.get_task("a", "r1", tid)["success"]
    missing = sat.get_task("a", "r1", "ffffffff")
    assert not missing["success"]
    assert "not found" in missing["error"]


def test_update_status_and_subject() -> None:
    sat.init_todo_list("a", run_id="r1")
    tid = sat.add_task("a", "r1", subject="old")["task"]["id"]
    out = sat.update_task("a", "r1", tid, status="completed", subject="new")
    assert out["task"]["status"] == "completed"
    assert out["task"]["subject"] == "new"


def test_update_unknown_status_is_ignored() -> None:
    sat.init_todo_list("a", run_id="r1")
    tid = sat.add_task("a", "r1", subject="x")["task"]["id"]
    out = sat.update_task("a", "r1", tid, status="bogus")
    assert out["task"]["status"] == "pending"


def test_delete_removes_task() -> None:
    sat.init_todo_list("a", run_id="r1")
    tid = sat.add_task("a", "r1", subject="x")["task"]["id"]
    out = sat.delete_task("a", "r1", tid)
    assert out["success"] and out["deleted"] == tid
    assert sat.list_tasks("a", "r1")["task_count"] == 0


def test_clear_removes_file() -> None:
    sat.init_todo_list("a", run_id="r1")
    out = sat.clear_todo_list("a", "r1")
    assert "cleared" in out["message"]
    assert not sat.get_todo_file_path("a", "r1").exists()


def test_cleanup_removes_old_files_keeps_fresh(
    isolated_todos_dir: Path,
) -> None:
    sat.init_todo_list("fresh", run_id="r1")
    sat.init_todo_list("stale", run_id="r1")
    stale_path = sat.get_todo_file_path("stale", "r1")
    old_time = (datetime.now() - timedelta(days=2)).timestamp()
    os.utime(stale_path, (old_time, old_time))
    out = sat.cleanup_old_lists()
    assert out["cleaned"] == 1
    assert any("stale" in name for name in out["cleaned_files"])
    assert sat.get_todo_file_path("fresh", "r1").exists()
    assert not stale_path.exists()


def test_run_ids_isolate_concurrent_runs() -> None:
    sat.init_todo_list("agent", run_id="r1")
    sat.init_todo_list("agent", run_id="r2")
    sat.add_task("agent", "r1", subject="r1 task")
    sat.add_task("agent", "r2", subject="r2 task")
    r1 = sat.list_tasks("agent", "r1")
    r2 = sat.list_tasks("agent", "r2")
    assert r1["tasks"][0]["subject"] == "r1 task"
    assert r2["tasks"][0]["subject"] == "r2 task"


def test_cli_init_command_emits_json(
    capsys: pytest.CaptureFixture[str], isolated_todos_dir: Path,
) -> None:
    rc = sat.main(["init", "agent", "--run-id", "r1"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["success"]


def test_cli_add_then_list_json(
    capsys: pytest.CaptureFixture[str], isolated_todos_dir: Path,
) -> None:
    sat.main(["init", "agent", "--run-id", "r1"])
    capsys.readouterr()
    sat.main([
        "add", "agent", "--run-id", "r1",
        "--subject", "do thing", "--description", "very important",
    ])
    capsys.readouterr()
    sat.main(["list", "agent", "--run-id", "r1", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["task_count"] == 1
    assert out["tasks"][0]["subject"] == "do thing"


def test_cli_supports_keyword_form_for_agent_and_task_id(
    capsys: pytest.CaptureFixture[str], isolated_todos_dir: Path,
) -> None:
    sat.main(["init", "--agent-name", "x", "--run-id", "r1"])
    capsys.readouterr()
    sat.main(["add", "--agent-name", "x", "--run-id", "r1", "--subject", "s"])
    capsys.readouterr()
    listing = sat.list_tasks("x", "r1")
    tid = listing["tasks"][0]["id"]
    sat.main([
        "update", "--agent-name", "x", "--task-id", tid, "--run-id", "r1",
        "--status", "completed",
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["task"]["status"] == "completed"


def test_xdg_data_home_used_when_oac_override_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OAC_TODOS_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    sat.init_todo_list("agent", run_id="r1")
    assert (tmp_path / "xdg" / "oac" / "agent_todos" / "todo_agent_r1.json").exists()
