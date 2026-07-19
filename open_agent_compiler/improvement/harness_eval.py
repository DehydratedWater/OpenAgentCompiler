"""Harness-agnostic eval runners — the pluggable "run a compiled agent" leg.

Until now the improvement loop's live evaluation leg was hard-wired to
opencode (`opencode_eval.OpencodeRunner`), so an autoloop could only
adapt an agent *to opencode*. This module generalizes that leg:

- :class:`HarnessResult` / :class:`HarnessRunner` — the structural
  contract every runner satisfies. `OpencodeRunner` already conforms;
  this module adds :class:`PiRunner` and :class:`CodexRunner` and a
  registry (:func:`get_runner` / :func:`register_runner`) keyed by
  dialect name, so `run_per_target_loops` (target_loop.py) can spin up
  the right runner for each `(harness, model_class)` target.

An evaluator built on this contract needs three things from a run:
`final_text()` (what the judge/evaluators score), `error` (a surfaced
failure that must not masquerade as an empty answer — the lesson
opencode_eval encodes), and `succeeded`. Everything richer (event
parsing, dispatch chains, blocked-tool details) stays harness-specific
on the concrete result types.

Runner caveats per harness:

- **pi** — invokes headless `pi -p --approve` in the build
  tree. Output is plain text (no JSON event stream), so `final_text()`
  is stdout. The build tree must have been compiled with
  `--dialect pi`, and the pi runtime needs its two extensions
  (pi-subagents + pi-permission-system) installed.
- **codex** — Codex has no `--agent` flag; custom agents are addressed
  by *asking* for them. `CodexRunner` therefore wraps the prompt in a
  delegation instruction naming the agent. The build tree must have
  been compiled with `--dialect codex` (so `.codex/agents/<name>.toml`
  and `AGENTS.md` exist for Codex to discover).
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from open_agent_compiler.improvement.opencode_eval import OpencodeRunner


@runtime_checkable
class HarnessResult(Protocol):
    """What an evaluator may rely on from any harness run."""

    @property
    def succeeded(self) -> bool: ...

    @property
    def error(self) -> str | None: ...

    def final_text(self) -> str: ...


@runtime_checkable
class HarnessRunner(Protocol):
    """A live invoker for one compiled-agent harness (opencode, pi, …)."""

    harness_name: str

    def run(
        self,
        *,
        agent_name: str,
        prompt: str,
        timeout_s: float | None = None,
    ) -> HarnessResult: ...


@dataclass
class SubprocessHarnessResult:
    """Plain-text result shared by runners without a structured event stream."""

    harness_name: str
    agent_name: str
    prompt: str
    stdout: str
    stderr: str
    return_code: int
    elapsed_s: float

    @property
    def succeeded(self) -> bool:
        return self.return_code == 0

    @property
    def error(self) -> str | None:
        """A surfaced failure, or None. An empty answer with a non-None
        error is a harness/provider failure, NOT the model returning
        nothing — evaluators must check this before trusting final_text()."""
        if self.return_code != 0:
            return (
                f"{self.harness_name} exit {self.return_code}:"
                f" {self.stderr_tail(300)}"
            )
        return None

    def final_text(self) -> str:
        return self.stdout.strip()

    def stderr_tail(self, chars: int = 500) -> str:
        return self.stderr[-chars:] if len(self.stderr) > chars else self.stderr


def _run_subprocess(
    *,
    harness_name: str,
    cmd: list[str],
    cwd: Path,
    agent_name: str,
    prompt: str,
    timeout_s: float,
    extra_env: dict[str, str] | None = None,
    retry_on_empty: bool = True,
    retry_backoff_s: float = 2.0,
) -> SubprocessHarnessResult:
    """One subprocess invocation, with the same empty-output safety net
    OpencodeRunner carries: an exit-0 run that produced no text is
    retried once — the rare transient blank otherwise quietly becomes
    score=None for an entire eval row."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    def _one_try() -> SubprocessHarnessResult:
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, cwd=str(cwd), env=env,
                capture_output=True, text=True, timeout=timeout_s,
            )
            return SubprocessHarnessResult(
                harness_name=harness_name,
                agent_name=agent_name, prompt=prompt,
                stdout=proc.stdout, stderr=proc.stderr,
                return_code=proc.returncode,
                elapsed_s=time.monotonic() - t0,
            )
        except subprocess.TimeoutExpired as exc:
            return SubprocessHarnessResult(
                harness_name=harness_name,
                agent_name=agent_name, prompt=prompt,
                stdout=exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "",
                stderr=(
                    (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
                    + f"\n[{harness_name}] timed out after {timeout_s}s"
                ),
                return_code=-1,
                elapsed_s=time.monotonic() - t0,
            )

    result = _one_try()
    if retry_on_empty and result.return_code == 0 and not result.final_text():
        time.sleep(retry_backoff_s)
        result = _one_try()
    return result


@dataclass
class PiRunner:
    """Sync headless `pi -p` invoker for a `--dialect pi` build tree.

    pi has no per-agent CLI flag; compiled `.pi/agents/*.md` files are
    SUBAGENT types provided by pi-subagents, so the runner asks the main
    pi agent to spawn the named agent via the Agent tool. `--approve`
    trusts the build tree's project-local agents/extensions for the run;
    `--no-session` keeps eval runs out of the session history.
    """

    build_dir: Path
    pi_bin: str = "pi"
    default_timeout_s: float = 180.0
    harness_name: str = "pi"
    retry_on_empty_output: bool = True
    retry_backoff_s: float = 2.0

    def run(
        self,
        *,
        agent_name: str,
        prompt: str,
        timeout_s: float | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> SubprocessHarnessResult:
        delegated = (
            f"Use the Agent tool to spawn the `{agent_name}` agent"
            " (foreground) for the following task, then return ONLY its"
            " result.\n\n" + prompt
        )
        cmd = [
            self.pi_bin, "-p", "--mode", "text", "--approve", "--no-session",
            delegated,
        ]
        return _run_subprocess(
            harness_name=self.harness_name, cmd=cmd, cwd=self.build_dir,
            agent_name=agent_name, prompt=delegated,
            timeout_s=timeout_s or self.default_timeout_s,
            extra_env=extra_env,
            retry_on_empty=self.retry_on_empty_output,
            retry_backoff_s=self.retry_backoff_s,
        )


@dataclass
class ClaudeCodeRunner:
    """Sync `claude -p` invoker for a `--dialect claude` build tree.

    Claude Code has no per-agent invocation flag for compiled subagents;
    like Codex, the runner addresses the agent through delegation
    phrasing and relies on the build tree's `.claude/agents/*.md` for
    discovery. Permissions come from the tree's `.claude/settings.json`
    (emitted by the claude dialect).
    """

    build_dir: Path
    claude_bin: str = "claude"
    default_timeout_s: float = 300.0
    harness_name: str = "claude"
    retry_on_empty_output: bool = True
    retry_backoff_s: float = 2.0

    def run(
        self,
        *,
        agent_name: str,
        prompt: str,
        timeout_s: float | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> SubprocessHarnessResult:
        delegated = (
            f"Use the `{agent_name}` subagent for the following task and"
            " return only its result.\n\n" + prompt
        )
        cmd = [self.claude_bin, "-p", delegated, "--output-format", "text"]
        return _run_subprocess(
            harness_name=self.harness_name, cmd=cmd, cwd=self.build_dir,
            agent_name=agent_name, prompt=delegated,
            timeout_s=timeout_s or self.default_timeout_s,
            extra_env=extra_env,
            retry_on_empty=self.retry_on_empty_output,
            retry_backoff_s=self.retry_backoff_s,
        )


@dataclass
class CodexRunner:
    """Sync `codex exec` invoker for a `--dialect codex` build tree.

    Codex has no per-agent invocation flag; the compiled custom agents
    are addressed through delegation phrasing. The runner prepends a
    one-line instruction naming the agent, relying on the build tree's
    `AGENTS.md` + `.codex/agents/<name>.toml` for discovery.
    """

    build_dir: Path
    codex_bin: str = "codex"
    default_timeout_s: float = 300.0
    harness_name: str = "codex"
    retry_on_empty_output: bool = True
    retry_backoff_s: float = 2.0

    def run(
        self,
        *,
        agent_name: str,
        prompt: str,
        timeout_s: float | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> SubprocessHarnessResult:
        delegated = (
            f"Spawn the `{agent_name}` custom agent as a subagent for the"
            " following task and return only its result.\n\n" + prompt
        )
        cmd = [self.codex_bin, "exec", delegated]
        return _run_subprocess(
            harness_name=self.harness_name, cmd=cmd, cwd=self.build_dir,
            agent_name=agent_name, prompt=delegated,
            timeout_s=timeout_s or self.default_timeout_s,
            extra_env=extra_env,
            retry_on_empty=self.retry_on_empty_output,
            retry_backoff_s=self.retry_backoff_s,
        )


# --- registry -----------------------------------------------------------
#
# Keyed by dialect name so target loops can resolve "the runner for this
# harness" the same way CompileScript resolves "the compiler for this
# dialect". External packages register their own via register_runner().

RunnerFactory = Callable[[Path], HarnessRunner]

_RUNNERS: dict[str, RunnerFactory] = {
    "opencode": lambda build_dir: OpencodeRunner(build_dir=build_dir),
    "pi": lambda build_dir: PiRunner(build_dir=build_dir),
    "codex": lambda build_dir: CodexRunner(build_dir=build_dir),
    "claude": lambda build_dir: ClaudeCodeRunner(build_dir=build_dir),
}


def register_runner(harness: str, factory: RunnerFactory) -> None:
    """Register (or override) the runner factory for a harness name."""
    _RUNNERS[harness] = factory


def list_runners() -> list[str]:
    return sorted(_RUNNERS)


def get_runner(harness: str, build_dir: Path) -> HarnessRunner:
    """Build the registered runner for `harness` against `build_dir`.

    Raises ValueError for an unknown harness — pass your own runner (or
    register_runner it) for harnesses this module doesn't bundle, e.g.
    "interactive" targets evaluate in-process via
    `open_agent_compiler.improvement.interactive_eval` instead of a
    subprocess runner.
    """
    if harness not in _RUNNERS:
        raise ValueError(
            f"no runner registered for harness {harness!r};"
            f" registered: {list_runners()}"
        )
    return _RUNNERS[harness](build_dir)
