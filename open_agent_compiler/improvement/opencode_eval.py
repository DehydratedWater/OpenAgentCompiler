"""Sync opencode runner for autoresearch evaluators.

The streaming runner (long_running.StreamingOpencodeRun) is for
live-progress monitoring. For "compile candidate → run eval set →
read scores" loops, the sync subprocess.run path is simpler,
matches the battle-tested production opencode-manager pattern,
and bypasses the empty-output failures that occasionally hit
rapid-sequential async invocations.

This module is the recommended path for autoresearch evaluators:

    from open_agent_compiler.improvement.opencode_eval import OpencodeRunner

    runner = OpencodeRunner(build_dir=Path("build"))
    result = runner.run(
        agent_name="transcript-scorer-primary",
        prompt="Score X against Y. JSON only.",
        timeout_s=120,
    )
    print(result.score_field("score"))  # → 0.85 or None
    print(result.json_objects(must_contain_key="score"))
    print(result.return_code, result.stderr_tail(200))

Includes a built-in retry-on-empty-output (one retry by default
with a backoff) so the rare transient zero-event run doesn't
silently produce score=None for an entire eval row.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OPENCODE_BIN_DEFAULT = "opencode"


# --- reusable pure parse helpers over the JSON event stream -----------------
# These are the production field-report safeguards, promoted into core so every
# consumer parses opencode output the same (correct) way instead of
# re-implementing — the re-implementation gap is exactly what let
# agent-discovery failures masquerade as the model "returning nothing" and
# score every affected agent 0.


def opencode_errors(stdout: str) -> list[str]:
    """Pull `{"type":"error", ...}` messages out of the JSON event stream.

    opencode reports failures (e.g. ``Agent not found``, provider/auth errors)
    as error events, NOT a non-zero exit. These MUST be surfaced — swallowing
    them as "empty assistant text" is what made a fleet of agent-discovery
    failures masquerade as the model "returning nothing" and score every
    affected agent 0. This is the single safeguard that catches that whole class.
    """
    out: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{") or '"type":"error"' not in line.replace(" ", ""):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "error":
            e = ev.get("error") or {}
            msg = ((e.get("data") or {}).get("message")
                   if isinstance(e, dict) else None) or json.dumps(e)[:200]
            out.append(str(msg))
    return out


def subagent_dispatch_chain(stdout: str) -> list[tuple[str, dict[str, Any]]]:
    """Extract an ORCHESTRATOR's sub-agent dispatch chain from the event stream.

    Orchestrators frequently spawn sub-agents via a bash command
    (``… opencode … run --agent <name> …``) rather than a structured Task tool
    part — so the raw tool calls are all ``bash`` and the real chain is hidden in
    the bash command string. This pulls the dispatched agent names out so
    branch/path grading can see the trajectory. Returns ``(name, {"via": "spawn"})``
    pairs (kept dependency-free; callers can wrap them into their own record type).
    """
    chain: list[tuple[str, dict[str, Any]]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{") or "--agent" not in line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") if isinstance(ev, dict) else None
        if not isinstance(part, dict):
            continue
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        inp = state.get("input") if isinstance(state.get("input"), dict) else {}
        args = part.get("args") if isinstance(part.get("args"), dict) else {}
        cmd = inp.get("command") or args.get("command") or ""
        if "--agent" not in cmd:
            continue
        m = re.search(r"--agent\s+[\"']?([A-Za-z0-9_/.-]+)", cmd)
        if m:
            chain.append((m.group(1), {"via": "spawn"}))
    return chain


def blocked_tool_details(stdout: str) -> list[tuple[str, str]]:
    """The DENIED tool attempts in this session as ``(tool_name, reason)`` pairs.

    Same detection as :func:`blocked_tool_attempts` (a tool part whose state
    output/error says the permission policy "prevents you from using" it), but
    returns the tool NAME and the deny reason for each — the signal a judge /
    prompt-rewriter needs to learn WHICH forbidden tools the model flailed on,
    not just how many. The tool name is best-effort across part shapes (falls
    back to ``"?"`` when opencode doesn't name the part).
    """
    out: list[tuple[str, str]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{") or "prevents you from using" not in line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") if isinstance(ev, dict) else None
        if not isinstance(part, dict):
            continue
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        reason = str(state.get("output") or state.get("error") or "")
        if "prevents you from using" not in reason:
            continue
        # best-effort tool name across shapes: part.tool{.name}, part.name, …
        name = ""
        tool = part.get("tool")
        if isinstance(tool, dict):
            name = str(tool.get("name") or "")
        if not name:
            for key in ("tool", "name", "agent"):
                v = part.get(key)
                if isinstance(v, str) and v:
                    name = v
                    break
        out.append((name or "?", reason.strip()[:200]))
    return out


def blocked_tool_attempts(stdout: str) -> int:
    """Count tool calls the permission policy DENIED in this session.

    Agents are compiled with an allow-list (e.g. ``python scripts/<tools>.py``).
    When a tool fails, a model tends to debug-flail on forbidden commands
    (``pip install``, ``which python``, ``ls``, ``python3 -c …``) — all denied,
    retried repeatedly, wasting the turn and tanking the score. A high count is a
    behavioural smell (bad env or a prompt that invites flailing); unit tests
    can't see it, but a live smoke can assert this stays low.
    """
    return len(blocked_tool_details(stdout))


def flailing_note(
    blocked: list[tuple[str, str]] | None, error: str | None,
) -> str:
    """Render the tool-discipline / session-error signal for the JUDGE.

    The scoring blind-spot this closes: a strict allow-list DENIES a model's
    reflexive ``ls``/``read``/``find`` calls, and opencode can ERROR a whole
    session — but neither was forwarded to the judge, so it scored prose alone
    and the rubric clause that penalises "flailing on blocked tools" could never
    fire (and the rewriter never learned to avoid them). This builds an explicit,
    appendable note so the judge SEES the flailing and an empty turn is labelled
    as an error instead of presented as a blank.

    Returns ``""`` when there is nothing to report (clean run).
    """
    parts: list[str] = []
    if error:
        parts.append(
            "TOOL DISCIPLINE: the session ERRORED: " + str(error)[:300]
            + " — treat as a failed run, not an empty answer."
        )
    if blocked:
        names = ", ".join(dict.fromkeys(n for n, _ in blocked)) or "?"
        parts.append(
            f"TOOL DISCIPLINE: the agent made {len(blocked)} DENIED/blocked tool"
            f" attempt(s): [{names}] — these are forbidden by its allow-list; this"
            " is flailing and must lower the score."
        )
    return "\n".join(parts)


@dataclass
class OpencodeRunResult:
    """Captured output from one synchronous opencode run."""

    agent_name: str
    prompt: str
    stdout: str
    stderr: str
    return_code: int
    elapsed_s: float
    attempts: int = 1
    _texts_cache: list[str] | None = field(default=None, repr=False)

    @property
    def succeeded(self) -> bool:
        # An exit-0 run that nonetheless emitted an opencode error event (the
        # `Agent not found` class) did NOT succeed — never treat it as clean.
        return self.return_code == 0 and not self.errors()

    def errors(self) -> list[str]:
        """Surfaced ``{"type":"error"}`` event messages from the stream."""
        return opencode_errors(self.stdout)

    @property
    def error(self) -> str | None:
        """A single surfaced error string (first two joined), or None.

        This is the field consumers must check BEFORE trusting `final_text()`:
        an empty `final_text()` with a non-None `error` is a discovery/provider
        failure, NOT the model returning nothing.
        """
        errs = self.errors()
        if errs:
            return "opencode error: " + " | ".join(errs[:2])
        if self.return_code not in (0,) and not self.final_text().strip():
            return f"opencode exit {self.return_code}: {self.stderr_tail(300)}"
        return None

    def subagent_dispatch_chain(self) -> list[tuple[str, dict[str, Any]]]:
        """The orchestrator sub-agent dispatch chain parsed from this run."""
        return subagent_dispatch_chain(self.stdout)

    def blocked_tool_attempts(self) -> int:
        """How many tool calls the permission policy denied in this run."""
        return blocked_tool_attempts(self.stdout)

    def blocked_tool_details(self) -> list[tuple[str, str]]:
        """The denied tool attempts as ``(tool_name, reason)`` pairs.

        The signal the judge / rewriter needs to learn WHICH forbidden tools the
        model flailed on (so the prompt can be rewritten to avoid them), not just
        a count.
        """
        return blocked_tool_details(self.stdout)

    def text_segments(self) -> list[str]:
        """Pull every `text` + tool-output field out of the JSON event stream."""
        if self._texts_cache is not None:
            return self._texts_cache
        texts: list[str] = []
        for line in self.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            part = ev.get("part", {}) if isinstance(ev, dict) else {}
            if isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    texts.append(part["text"])
                state = part.get("state")
                if isinstance(state, dict) and isinstance(state.get("output"), str):
                    texts.append(state["output"])
        self._texts_cache = texts
        return texts

    def final_text(self) -> str:
        return "\n".join(self.text_segments())

    def json_objects(
        self, *, must_contain_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find every well-formed JSON object emitted in the agent's output.

        Strips markdown code fences (```json ... ```) and tries to
        load each candidate. Filters by `must_contain_key` so
        downstream code can pick the right object without guessing.
        """
        blob = self.final_text()
        # Greedy: matches flat objects; agent outputs are usually shallow.
        candidates = re.findall(r"\{[^{}]+\}", blob, flags=re.DOTALL)
        out: list[dict[str, Any]] = []
        for cand in candidates:
            try:
                obj = json.loads(cand)
            except json.JSONDecodeError:
                continue
            if must_contain_key is not None and must_contain_key not in obj:
                continue
            out.append(obj)
        return out

    def score_field(
        self,
        field_name: str = "score",
        *,
        clamp_to_range: tuple[float, float] | None = (0.0, 1.0),
    ) -> float | None:
        """Extract a single numeric score from the final output.

        Searches the concatenated text for `"<field_name>": <number>`.
        When `clamp_to_range` is set (default `(0, 1)`), returns None
        for any value outside the range — protects evaluators against
        agents that drift the output scale (e.g., returning 8 when
        the rubric is 0-1).
        """
        blob = self.final_text()
        m = re.search(rf'"{re.escape(field_name)}"\s*:\s*([0-9.]+)', blob)
        if not m:
            return None
        try:
            v = float(m.group(1))
        except ValueError:
            return None
        if clamp_to_range is not None:
            lo, hi = clamp_to_range
            if v < lo or v > hi:
                return None
        return v

    def stderr_tail(self, chars: int = 500) -> str:
        return self.stderr[-chars:] if len(self.stderr) > chars else self.stderr


@dataclass
class OpencodeRunner:
    """Sync subprocess.run-based opencode invoker for eval loops.

    Satisfies the `HarnessRunner` protocol (harness_eval.py) so target
    loops can treat opencode as one harness among several.
    """

    build_dir: Path
    opencode_bin: str = OPENCODE_BIN_DEFAULT
    harness_name: str = "opencode"
    default_timeout_s: float = 180.0
    # Auto-retry once when stdout has zero parseable text events.
    # The empty-output failure is rare (~1 in 20 in stress testing)
    # but quietly turns into score=None without this safety net.
    retry_on_empty_output: bool = True
    retry_backoff_s: float = 2.0

    def run(
        self,
        *,
        agent_name: str,
        prompt: str,
        timeout_s: float | None = None,
        extra_env: dict[str, str] | None = None,
        extra_args: list[str] | None = None,
    ) -> OpencodeRunResult:
        env = os.environ.copy()
        env["XDG_DATA_HOME"] = str(self.build_dir / ".opencode" / "data")
        env["PWD"] = str(self.build_dir)
        if extra_env:
            env.update(extra_env)
        cmd = [
            self.opencode_bin, "run",
            "--agent", agent_name, "--format", "json",
            *(extra_args or []),
            prompt,
        ]

        def _one_try(attempt_no: int) -> OpencodeRunResult:
            t0 = time.monotonic()
            try:
                proc = subprocess.run(
                    cmd, cwd=str(self.build_dir), env=env,
                    capture_output=True, text=True,
                    timeout=timeout_s or self.default_timeout_s,
                )
                return OpencodeRunResult(
                    agent_name=agent_name, prompt=prompt,
                    stdout=proc.stdout, stderr=proc.stderr,
                    return_code=proc.returncode,
                    elapsed_s=time.monotonic() - t0,
                    attempts=attempt_no,
                )
            except subprocess.TimeoutExpired as exc:
                return OpencodeRunResult(
                    agent_name=agent_name, prompt=prompt,
                    stdout=exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "",
                    stderr=(
                        (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
                        + f"\n[OpencodeRunner] timed out after {timeout_s}s"
                    ),
                    return_code=-1,
                    elapsed_s=time.monotonic() - t0,
                    attempts=attempt_no,
                )

        result = _one_try(1)
        if (
            self.retry_on_empty_output
            and result.return_code == 0
            and (not result.text_segments() or result.errors())
        ):
            # Transient empty-output OR a surfaced error event (the
            # `Agent not found` discovery class exits 0 but is retryable):
            # pause + try once more.
            time.sleep(self.retry_backoff_s)
            result = _one_try(2)
        return result
