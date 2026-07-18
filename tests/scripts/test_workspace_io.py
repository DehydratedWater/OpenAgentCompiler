"""Bundled workspace_io.py — sandboxed, run-id-isolated FS access."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_agent_compiler.scripts import workspace_io as wio


def test_init_creates_session_dir_and_returns_run_id(tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    result = wio.cmd_init(str(ws_root))
    assert result["success"]
    assert result["run_id"]
    assert Path(result["path"]).exists()
    assert Path(result["path"]).parent.resolve() == ws_root.resolve()


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    ws = wio._resolve_workspace(str(tmp_path / "ws"), run_id="r1")
    wio.cmd_write(ws, "note.txt", "hello there")
    out = wio.cmd_read(ws, "note.txt")
    assert out["success"]
    assert out["content"] == "hello there"


def test_read_missing_file_reports_error(tmp_path: Path) -> None:
    ws = wio._resolve_workspace(str(tmp_path / "ws"), run_id="r1")
    out = wio.cmd_read(ws, "ghost.txt")
    assert not out["success"]
    assert "not found" in out["error"]


def test_list_returns_relative_paths(tmp_path: Path) -> None:
    ws = wio._resolve_workspace(str(tmp_path / "ws"), run_id="r1")
    wio.cmd_write(ws, "a.txt", "1")
    wio.cmd_write(ws, "sub/b.txt", "2")
    out = wio.cmd_list(ws)
    assert out["count"] == 2
    assert "a.txt" in out["files"]
    assert "sub/b.txt" in out["files"]


def test_delete_removes_file(tmp_path: Path) -> None:
    ws = wio._resolve_workspace(str(tmp_path / "ws"), run_id="r1")
    wio.cmd_write(ws, "a.txt", "1")
    out = wio.cmd_delete(ws, "a.txt")
    assert out["success"] and out["deleted"] is True
    assert not (ws / "a.txt").exists()


def test_delete_missing_file_reports_error(tmp_path: Path) -> None:
    ws = wio._resolve_workspace(str(tmp_path / "ws"), run_id="r1")
    out = wio.cmd_delete(ws, "ghost.txt")
    assert not out["success"]


def test_path_traversal_denied(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    ws = wio._resolve_workspace(str(tmp_path / "ws"), run_id="r1")
    with pytest.raises(SystemExit) as exc:
        wio._safe_path(ws, "../../etc/passwd")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Path traversal denied" in err


def test_run_id_isolation(tmp_path: Path) -> None:
    ws_root = str(tmp_path / "ws")
    ws1 = wio._resolve_workspace(ws_root, run_id="r1")
    ws2 = wio._resolve_workspace(ws_root, run_id="r2")
    wio.cmd_write(ws1, "x.txt", "from r1")
    wio.cmd_write(ws2, "x.txt", "from r2")
    assert wio.cmd_read(ws1, "x.txt")["content"] == "from r1"
    assert wio.cmd_read(ws2, "x.txt")["content"] == "from r2"


def test_xdg_data_home_prefixes_relative_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    out = wio.cmd_init("agent-ws")
    assert Path(out["path"]).is_relative_to(tmp_path / "xdg" / "oac")


def test_absolute_workspace_paths_skip_xdg_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    abs_ws = tmp_path / "absolute-ws"
    out = wio.cmd_init(str(abs_ws))
    assert Path(out["path"]).is_relative_to(abs_ws)


# ---- main() CLI entry ----------------------------------------------------


def test_cli_init(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rc = wio.main(["--command", "init", "--workspace", str(tmp_path / "ws")])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["success"]
    assert "run_id" in out


def test_cli_write_then_read(
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    ws_root = str(tmp_path / "ws")
    wio.main([
        "--command", "write", "--workspace", ws_root, "--run-id", "r1",
        "--filename", "note.txt",
    ], stdin_content="payload")
    capsys.readouterr()
    rc = wio.main([
        "--command", "read", "--workspace", ws_root, "--run-id", "r1",
        "--filename", "note.txt",
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["content"] == "payload"


def test_cli_missing_filename_errors_with_actionable_message(
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    rc = wio.main([
        "--command", "write", "--workspace", str(tmp_path / "ws"),
        "--run-id", "r1",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "--filename required" in err
