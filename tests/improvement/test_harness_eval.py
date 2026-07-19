"""Harness-agnostic runners: protocol conformance, subprocess runners, registry."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from open_agent_compiler.improvement.harness_eval import (
    CodexRunner,
    HarnessResult,
    HarnessRunner,
    PiRunner,
    SubprocessHarnessResult,
    get_runner,
    list_runners,
    register_runner,
)
from open_agent_compiler.improvement.opencode_eval import OpencodeRunner


def _write_stub_bin(path: Path, *, exit_code: int = 0, echo_prefix: str = "") -> Path:
    """A tiny shell stub standing in for the pi/codex binary.

    Prints its argv (so tests can assert the constructed command) and
    exits with `exit_code`.
    """
    path.write_text(
        "#!/bin/sh\n"
        f'echo "{echo_prefix}$@"\n'
        'echo "stub-stderr" >&2\n'
        f"exit {exit_code}\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


# ---- protocol conformance ---------------------------------------------


def test_opencode_runner_satisfies_harness_protocol(tmp_path: Path) -> None:
    assert isinstance(OpencodeRunner(build_dir=tmp_path), HarnessRunner)


def test_pi_and_codex_runners_satisfy_harness_protocol(tmp_path: Path) -> None:
    assert isinstance(PiRunner(build_dir=tmp_path), HarnessRunner)
    assert isinstance(CodexRunner(build_dir=tmp_path), HarnessRunner)


def test_subprocess_result_satisfies_result_protocol() -> None:
    res = SubprocessHarnessResult(
        harness_name="pi", agent_name="a", prompt="p",
        stdout="out", stderr="", return_code=0, elapsed_s=0.1,
    )
    assert isinstance(res, HarnessResult)


# ---- PiRunner ----------------------------------------------------------


def test_pi_runner_invokes_pi_run_agent(tmp_path: Path) -> None:
    stub = _write_stub_bin(tmp_path / "pi-stub")
    runner = PiRunner(build_dir=tmp_path, pi_bin=str(stub))
    result = runner.run(agent_name="summarizer", prompt="hello world")
    assert result.succeeded
    assert result.error is None
    # The stub echoes argv: `run --agent summarizer hello world`
    assert "run --agent summarizer hello world" in result.final_text()


def test_pi_runner_nonzero_exit_surfaces_error(tmp_path: Path) -> None:
    stub = _write_stub_bin(tmp_path / "pi-stub", exit_code=3)
    runner = PiRunner(build_dir=tmp_path, pi_bin=str(stub))
    result = runner.run(agent_name="x", prompt="p")
    assert not result.succeeded
    assert result.error is not None
    assert "exit 3" in result.error
    assert "stub-stderr" in result.error


# ---- CodexRunner -------------------------------------------------------


def test_codex_runner_wraps_prompt_in_delegation(tmp_path: Path) -> None:
    stub = _write_stub_bin(tmp_path / "codex-stub")
    runner = CodexRunner(build_dir=tmp_path, codex_bin=str(stub))
    result = runner.run(agent_name="critic", prompt="judge this")
    assert result.succeeded
    text = result.final_text()
    assert text.startswith("exec ")
    assert "`critic`" in text
    assert "judge this" in text


# ---- registry ----------------------------------------------------------


def test_builtin_runners_registered() -> None:
    names = list_runners()
    assert "opencode" in names
    assert "pi" in names
    assert "codex" in names


def test_get_runner_builds_against_build_dir(tmp_path: Path) -> None:
    runner = get_runner("pi", tmp_path)
    assert isinstance(runner, PiRunner)
    assert runner.build_dir == tmp_path


def test_get_runner_unknown_raises() -> None:
    with pytest.raises(ValueError, match="no runner registered"):
        get_runner("does-not-exist", Path("."))


def test_register_runner_adds_custom(tmp_path: Path) -> None:
    class _Stub:
        harness_name = "stub-harness"

        def __init__(self, build_dir: Path) -> None:
            self.build_dir = build_dir

        def run(self, *, agent_name, prompt, timeout_s=None):  # pragma: no cover
            raise NotImplementedError

    register_runner("stub-harness", _Stub)
    assert "stub-harness" in list_runners()
    assert isinstance(get_runner("stub-harness", tmp_path), _Stub)
