"""opencode error surfacing + parse helpers (Phase 0 hardening).

These pin the v4 field-report safeguards now living in core: an exit-0 run
that emitted `{"type":"error"}` (the `Agent not found` discovery class) must
NEVER pass as clean/empty text; the dispatch-chain + blocked-tool detectors
parse the JSON event stream the same way the consumer's runner did.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from open_agent_compiler.improvement.opencode_eval import (
    OpencodeRunResult,
    OpencodeRunner,
    blocked_tool_attempts,
    blocked_tool_details,
    flailing_note,
    opencode_errors,
    subagent_dispatch_chain,
)


def _make_stdout(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


def _result(stdout: str = "", *, rc: int = 0, stderr: str = "") -> OpencodeRunResult:
    return OpencodeRunResult(
        agent_name="x", prompt="p", stdout=stdout, stderr=stderr,
        return_code=rc, elapsed_s=0.0,
    )


# --- opencode_errors --------------------------------------------------------

def test_opencode_errors_extracts_message() -> None:
    stdout = _make_stdout(
        {"type": "error", "error": {"data": {"message": "Agent not found: a/b"}}},
        {"type": "text", "part": {"text": ""}},
    )
    assert opencode_errors(stdout) == ["Agent not found: a/b"]


def test_opencode_errors_empty_when_clean() -> None:
    stdout = _make_stdout({"type": "text", "part": {"text": "hello"}})
    assert opencode_errors(stdout) == []


def test_error_event_not_swallowed_as_empty_text() -> None:
    """The mass-zero root cause: exit-0 + error event must surface as error."""
    stdout = _make_stdout(
        {"type": "error", "error": {"data": {"message": "Agent not found"}}},
    )
    r = _result(stdout, rc=0)
    assert r.final_text() == ""        # no assistant text
    assert r.error is not None         # but the error IS surfaced
    assert "Agent not found" in r.error
    assert r.succeeded is False        # exit-0 with an error event is NOT success


def test_succeeded_true_only_on_clean_run() -> None:
    r = _result(_make_stdout({"type": "text", "part": {"text": "ok"}}), rc=0)
    assert r.succeeded is True
    assert r.error is None


def test_nonzero_exit_with_no_text_surfaces_error() -> None:
    r = _result("", rc=2, stderr="boom")
    assert r.error is not None
    assert "exit 2" in r.error


# --- subagent_dispatch_chain ------------------------------------------------

def test_dispatch_chain_parses_agent_from_bash_command() -> None:
    stdout = _make_stdout(
        {"part": {"type": "tool", "state": {
            "input": {"command": "opencode run --agent planner-primary 'go'"}}}},
        {"part": {"type": "tool", "state": {
            "input": {"command": "opencode run --agent writer-primary 'go'"}}}},
        {"part": {"type": "text", "text": "done"}},
    )
    chain = subagent_dispatch_chain(stdout)
    assert [name for name, _ in chain] == ["planner-primary", "writer-primary"]
    assert all(meta == {"via": "spawn"} for _, meta in chain)


def test_dispatch_chain_handles_args_command_shape() -> None:
    stdout = _make_stdout(
        {"part": {"type": "tool", "args": {"command": "x --agent foo 'hi'"}}},
    )
    assert [n for n, _ in subagent_dispatch_chain(stdout)] == ["foo"]


def test_dispatch_chain_empty_without_agent_flag() -> None:
    stdout = _make_stdout({"part": {"type": "text", "text": "no dispatch"}})
    assert subagent_dispatch_chain(stdout) == []


# --- blocked_tool_attempts --------------------------------------------------

def test_blocked_tool_attempts_counts_denials() -> None:
    stdout = _make_stdout(
        {"part": {"state": {"output": "permission prevents you from using bash"}}},
        {"part": {"state": {"error": "this prevents you from using pip"}}},
        {"part": {"state": {"output": "fine"}}},
    )
    assert blocked_tool_attempts(stdout) == 2


def test_blocked_tool_attempts_zero_when_clean() -> None:
    stdout = _make_stdout({"part": {"text": "all good"}})
    assert blocked_tool_attempts(stdout) == 0


# --- blocked_tool_details (names + reasons) ---------------------------------

def test_blocked_tool_details_returns_names_and_reasons() -> None:
    stdout = _make_stdout(
        {"part": {"tool": {"name": "ls"},
                  "state": {"error": "a rule prevents you from using ls"}}},
        {"part": {"name": "read",
                  "state": {"output": "a rule prevents you from using read"}}},
        {"part": {"state": {"output": "fine"}}},
    )
    details = blocked_tool_details(stdout)
    assert [n for n, _ in details] == ["ls", "read"]
    assert "prevents you from using ls" in details[0][1]
    # the count helper stays consistent with the detail list
    assert blocked_tool_attempts(stdout) == 2


def test_blocked_tool_details_unnamed_part_falls_back() -> None:
    stdout = _make_stdout(
        {"part": {"state": {"error": "a rule prevents you from using something"}}},
    )
    assert blocked_tool_details(stdout)[0][0] == "?"


def test_result_exposes_blocked_tool_details() -> None:
    stdout = _make_stdout(
        {"part": {"tool": {"name": "find"},
                  "state": {"error": "a rule prevents you from using find"}}},
    )
    assert _result(stdout).blocked_tool_details() == [
        ("find", "a rule prevents you from using find"),
    ]


# --- flailing_note (judge-facing render) ------------------------------------

def test_flailing_note_empty_when_clean() -> None:
    assert flailing_note([], None) == ""


def test_flailing_note_reports_blocked_tools() -> None:
    note = flailing_note(
        [("ls", "r1"), ("find", "r2"), ("ls", "r3")], None,
    )
    assert "TOOL DISCIPLINE" in note
    assert "3 DENIED/blocked tool" in note
    # de-duplicated tool name list
    assert "[ls, find]" in note


def test_flailing_note_labels_session_error() -> None:
    note = flailing_note([], "opencode error: Agent not found")
    assert "session ERRORED" in note
    assert "Agent not found" in note


def test_tool_call_record_carries_error_field() -> None:
    """The blocked/errored tool part reason rides on the record (additive field)."""
    from open_agent_compiler.testing.evaluation import ToolCallRecord

    rec = ToolCallRecord(name="ls", error="a rule prevents you from using ls")
    assert rec.error == "a rule prevents you from using ls"
    assert ToolCallRecord(name="read").error is None


# --- runner retries on a surfaced error event -------------------------------

def test_runner_retries_on_surfaced_error_event(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_run(cmd, *, cwd, env, capture_output, text, timeout):
        calls.append(cmd)
        if len(calls) == 1:
            # exit-0 but an error event — must be treated as retryable.
            stdout = _make_stdout(
                {"type": "error", "error": {"data": {"message": "Agent not found"}}},
            )
        else:
            stdout = _make_stdout({"type": "text", "part": {"text": "recovered"}})
        return type("Proc", (), {"stdout": stdout, "stderr": "",
                                 "returncode": 0})()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(time, "sleep", lambda *a: None)

    runner = OpencodeRunner(build_dir=tmp_path / "build")
    result = runner.run(agent_name="x", prompt="p")
    assert result.attempts == 2
    assert result.error is None
    assert result.final_text() == "recovered"
