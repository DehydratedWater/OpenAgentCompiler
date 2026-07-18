"""Long-running autoresearch runner — async-streaming, no wall-clock timeout.

Multi-agent orchestrations can easily exceed 5-10 minutes per eval
candidate (each subagent invocation through Task adds latency). A
sync `subprocess.run(..., timeout=N)` truncates these silently and
leaves snapshots half-written.

This module wraps opencode in `asyncio.create_subprocess_exec` and
streams its `--format json` event log line-by-line, dispatching each
event to a callback. The driver decides whether to keep waiting,
cancel, or move on — no fixed wall-clock cap.

Pattern:

    from open_agent_compiler.improvement.long_running import (
        StreamingOpencodeRun, OpencodeEventTap,
    )

    async def eval_one(agent_name, prompt):
        tap = OpencodeEventTap()
        async with StreamingOpencodeRun(
            build_dir=Path("build"),
            agent_name=agent_name,
            prompt=prompt,
            event_tap=tap,
        ) as run:
            await run.wait_until_idle(idle_seconds=30)
            # Or: await run.wait_for_event(predicate=lambda e: ...)
        return tap.extract_final_text()

`wait_until_idle` waits until N seconds have passed with no new
events streamed. Useful when you don't know how long the agent will
take but you DO know when it's stopped producing.

`wait_for_event` waits for a specific predicate (e.g., a text event
containing JSON). Either resolves the future or fires when the
process exits.

`event_tap` accumulates structured events the caller can replay
later (text spans, tool calls, tool results, costs).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StreamedEvent:
    """One line out of opencode --format json, parsed + classified."""

    kind: str                 # 'text' / 'tool_use' / 'step_start' / …
    raw: dict[str, Any]
    text: str | None = None   # extracted text content when applicable
    tool: str | None = None
    received_at: float = field(default_factory=time.monotonic)


@dataclass
class OpencodeEventTap:
    """Accumulates structured events the long-running run emits.

    Use to extract structured outputs (final text, JSON payloads,
    tool calls) once the run is idle, without re-parsing the raw
    stdout.
    """

    events: list[StreamedEvent] = field(default_factory=list)
    last_event_at: float = field(
        default_factory=time.monotonic,
        init=False,
    )

    def feed(self, event: StreamedEvent) -> None:
        self.events.append(event)
        self.last_event_at = event.received_at

    def extract_final_text(self) -> str:
        """Concatenate all text + tool-output content in stream order."""
        parts: list[str] = []
        for ev in self.events:
            if ev.text:
                parts.append(ev.text)
        return "\n".join(parts)

    def extract_json_objects(
        self, *, must_contain_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find every well-formed JSON object in the text stream.

        Use to recover structured agent output (e.g. the scorer's
        {score, rationale} dict) regardless of whether the model
        wrapped it in a code block or returned it inline.
        """
        blob = self.extract_final_text()
        # Greedy: skipping nested braces is fine because agent JSON
        # outputs are typically single-level. For nested payloads use
        # a real parser pass after locating the start brace.
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


def _classify(line: str) -> StreamedEvent | None:
    """Parse one opencode --format json line into a StreamedEvent."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type") or "unknown"
    part = raw.get("part", {}) if isinstance(raw.get("part"), dict) else {}
    text: str | None = None
    tool: str | None = None
    if isinstance(part.get("text"), str):
        text = part["text"]
    if isinstance(part, dict):
        if part.get("type") == "tool":
            tool = part.get("tool")
            state = part.get("state", {})
            if isinstance(state, dict):
                out = state.get("output")
                if isinstance(out, str):
                    # Tool output frequently contains the agent's final
                    # answer when invoked via Task; surface it.
                    text = (text + "\n" + out) if text else out
    return StreamedEvent(kind=kind, raw=raw, text=text, tool=tool)


class StreamingOpencodeRun:
    """Async context manager wrapping `opencode run --format json`."""

    def __init__(
        self,
        *,
        build_dir: Path,
        agent_name: str,
        prompt: str,
        event_tap: OpencodeEventTap,
        opencode_bin: str = "opencode",
        env: dict[str, str] | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        self.build_dir = build_dir
        self.agent_name = agent_name
        self.prompt = prompt
        self.tap = event_tap
        self.opencode_bin = opencode_bin
        self._env = env
        self._extra_args = extra_args or []
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_buf: list[str] = []

    async def __aenter__(self) -> "StreamingOpencodeRun":
        env = os.environ.copy()
        env["XDG_DATA_HOME"] = str(self.build_dir / ".opencode" / "data")
        env["PWD"] = str(self.build_dir)
        if self._env:
            env.update(self._env)
        cmd = [
            self.opencode_bin, "run",
            "--agent", self.agent_name, "--format", "json",
            *self._extra_args, self.prompt,
        ]
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(self.build_dir), env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()

    async def _read_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                return
            ev = _classify(line.decode("utf-8", errors="replace"))
            if ev is not None:
                self.tap.feed(ev)

    async def _read_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                return
            self._stderr_buf.append(line.decode("utf-8", errors="replace"))

    @property
    def stderr(self) -> str:
        return "".join(self._stderr_buf)

    async def wait_until_idle(
        self, *, idle_seconds: float = 30.0,
        max_total_seconds: float | None = None,
    ) -> bool:
        """Block until the event stream has been quiet for `idle_seconds`.

        Returns True when idle reached, False when the process exits
        first (with whatever events were captured) OR max_total_seconds
        elapses. Unlike `subprocess.run(timeout=N)`, this does NOT kill
        the process on timeout — the caller's __aexit__ does that
        cleanly.
        """
        started = time.monotonic()
        while True:
            await asyncio.sleep(min(idle_seconds, 2.0))
            if self._proc and self._proc.returncode is not None:
                # Drain pending stdout before returning so the caller
                # sees the complete event history. Fast-finishing runs
                # (~8-12s) typically still have buffered text events
                # the reader task hasn't pumped through yet.
                if self._reader_task is not None:
                    try:
                        await asyncio.wait_for(self._reader_task, timeout=5)
                    except asyncio.TimeoutError:
                        pass
                return False
            quiet_for = time.monotonic() - self.tap.last_event_at
            if quiet_for >= idle_seconds:
                return True
            if (
                max_total_seconds is not None
                and time.monotonic() - started > max_total_seconds
            ):
                return False

    async def wait_for_event(
        self,
        *,
        predicate: Callable[[StreamedEvent], bool],
        max_total_seconds: float | None = None,
    ) -> StreamedEvent | None:
        """Resolve when any captured event satisfies `predicate`."""
        started = time.monotonic()
        # Check accumulated events first.
        for ev in self.tap.events:
            if predicate(ev):
                return ev
        while True:
            await asyncio.sleep(0.5)
            if self.tap.events and predicate(self.tap.events[-1]):
                return self.tap.events[-1]
            if self._proc and self._proc.returncode is not None:
                return None
            if (
                max_total_seconds is not None
                and time.monotonic() - started > max_total_seconds
            ):
                return None

    async def wait_for_exit(self) -> int:
        """Block until the underlying process exits; returns the rc."""
        assert self._proc
        return await self._proc.wait()
