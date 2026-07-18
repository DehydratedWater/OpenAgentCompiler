"""OpencodeRunner sync eval runner — JSON parsing + scale validation + retry."""

from __future__ import annotations

import json
import time
from pathlib import Path


from open_agent_compiler.improvement.opencode_eval import (
    OpencodeRunResult,
    OpencodeRunner,
)


def _make_stdout(*events: dict) -> str:
    """Build a JSON-line event stream like opencode emits."""
    return "\n".join(json.dumps(e) for e in events)


def _result(stdout: str = "", *, rc: int = 0, stderr: str = "") -> OpencodeRunResult:
    return OpencodeRunResult(
        agent_name="x", prompt="p", stdout=stdout, stderr=stderr,
        return_code=rc, elapsed_s=0.0,
    )


def test_text_segments_extracts_text_and_tool_output_fields() -> None:
    stdout = _make_stdout(
        {"type": "text", "part": {"text": "hello"}},
        {"type": "tool_use", "part": {"type": "tool", "tool": "task",
                                       "state": {"output": "tool result"}}},
        {"type": "step_finish"},  # no text/output — skipped
    )
    r = _result(stdout)
    assert r.text_segments() == ["hello", "tool result"]
    assert r.final_text() == "hello\ntool result"


def test_score_field_finds_score_in_text() -> None:
    stdout = _make_stdout(
        {"type": "text", "part": {"text": '```json\n{"score": 0.85}\n```'}},
    )
    assert _result(stdout).score_field("score") == 0.85


def test_score_field_returns_none_when_no_score() -> None:
    stdout = _make_stdout(
        {"type": "text", "part": {"text": "I cannot score this."}},
    )
    assert _result(stdout).score_field("score") is None


def test_score_field_clamps_off_scale_to_none_by_default() -> None:
    """Agent drift: returning 8 when rubric is 0-1 → None (not 8.0)."""
    stdout = _make_stdout(
        {"type": "text", "part": {"text": '{"score": 8}'}},
    )
    assert _result(stdout).score_field("score") is None
    # But within range stays parsed.
    stdout_ok = _make_stdout({"type": "text", "part": {"text": '{"score": 0.6}'}})
    assert _result(stdout_ok).score_field("score") == 0.6


def test_score_field_clamp_disabled_passes_through() -> None:
    stdout = _make_stdout(
        {"type": "text", "part": {"text": '{"score": 7.5}'}},
    )
    assert _result(stdout).score_field("score", clamp_to_range=None) == 7.5


def test_score_field_clamp_custom_range() -> None:
    stdout = _make_stdout(
        {"type": "text", "part": {"text": '{"score": 7}'}},
    )
    assert _result(stdout).score_field("score", clamp_to_range=(0, 10)) == 7.0


def test_json_objects_filters_by_required_key() -> None:
    stdout = _make_stdout(
        {"type": "text", "part": {"text": '{"foo": 1}'}},
        {"type": "text", "part": {"text": '{"score": 0.5, "rationale": "x"}'}},
    )
    objs = _result(stdout).json_objects(must_contain_key="score")
    assert objs == [{"score": 0.5, "rationale": "x"}]


def test_stderr_tail_truncates_long_stderr() -> None:
    r = _result(stderr="A" * 2000)
    assert len(r.stderr_tail(500)) == 500


def test_runner_retries_on_empty_output(tmp_path: Path, monkeypatch) -> None:
    """The empty-output retry path: rc=0 + zero text events → one retry."""
    calls = []

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout):
        calls.append(cmd)
        # First call returns empty; second call returns a real score.
        if len(calls) == 1:
            stdout = ""  # zero text events — triggers retry
        else:
            stdout = _make_stdout(
                {"type": "text", "part": {"text": '{"score": 0.7}'}},
            )
        return type("Proc", (), {"stdout": stdout, "stderr": "",
                                  "returncode": 0})()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(time, "sleep", lambda *a: None)  # skip the backoff

    runner = OpencodeRunner(build_dir=tmp_path / "build")
    result = runner.run(agent_name="x", prompt="p")
    assert result.attempts == 2
    assert result.score_field("score") == 0.7
    assert len(calls) == 2


def test_runner_no_retry_when_disabled(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout):
        calls.append(cmd)
        return type("Proc", (), {"stdout": "", "stderr": "",
                                  "returncode": 0})()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = OpencodeRunner(
        build_dir=tmp_path / "build",
        retry_on_empty_output=False,
    )
    result = runner.run(agent_name="x", prompt="p")
    assert result.attempts == 1
    assert len(calls) == 1


def test_runner_handles_timeout(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    def fake_run(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=a[0], timeout=10)

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = OpencodeRunner(
        build_dir=tmp_path / "build",
        retry_on_empty_output=False,  # don't retry timeouts
    )
    result = runner.run(agent_name="x", prompt="p", timeout_s=10)
    assert result.return_code == -1
    assert "timed out" in result.stderr


def test_runner_sets_xdg_data_home_and_pwd(tmp_path: Path, monkeypatch) -> None:
    """The runner must set XDG_DATA_HOME + PWD so opencode finds agents."""
    captured: dict = {}

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout):
        captured.update(env=env, cwd=cwd, cmd=cmd)
        return type("Proc", (), {"stdout": "", "stderr": "",
                                  "returncode": 0})()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = OpencodeRunner(
        build_dir=tmp_path / "build", retry_on_empty_output=False,
    )
    runner.run(agent_name="agent-x", prompt="hi")
    assert captured["cwd"] == str(tmp_path / "build")
    assert captured["env"]["XDG_DATA_HOME"] == str(tmp_path / "build" / ".opencode" / "data")
    assert captured["env"]["PWD"] == str(tmp_path / "build")
    assert "agent-x" in captured["cmd"]
