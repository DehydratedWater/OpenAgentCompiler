"""Optional event sink/emitter for the interactive target.

Two things in the framework want to *tell the outside world what they are
doing* while they run:

1. **LangChain tools** (and subagent-tools, which run the same way a tool
   runs) — so a chat UI can show "calling priority-manager…", "subagent
   finished", or a tool's own mid-run progress.
2. **Deterministic workflows** — a plain, non-LLM step sequence that wants to
   push "step 3/7" progress to the same place.

This module is deliberately runtime-agnostic and dependency-light (pydantic +
stdlib only): no LangChain import, so a deterministic workflow can emit events
without pulling the optional extra. The LangChain binding wires a sink in when
one is provided; with no sink the emitter is a no-op and nothing changes.

The shape is a classic sink/emitter split:

* a :class:`EventSink` is *where* events go (a callback, a queue, a list);
* an :class:`EventEmitter` is *what* produces them — bound to one sink and one
  ``source`` name, it stamps a monotonic ``seq`` and offers tool/progress
  conveniences. ``emitter.child(...)`` spawns a nested emitter (same sink, new
  source) for a subagent so its events are attributable yet share the stream.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


class EventKind:
    """Well-known event kinds. ``kind`` is a free-form string — these are the
    ones the binding emits automatically; consumers may emit their own."""

    TOOL_START = "tool.start"
    TOOL_END = "tool.end"
    TOOL_ERROR = "tool.error"
    # Subagents run *as tools*, so they reuse the tool.* kinds with the
    # subagent's name as `source`. These exist for consumers that want to
    # distinguish a subagent dispatch explicitly.
    SUBAGENT_START = "subagent.start"
    SUBAGENT_END = "subagent.end"
    # Mid-run progress — emitted by a tool/subagent/workflow while it works.
    PROGRESS = "progress"
    # A free-form message/log line (e.g. a streamed token batch a tool wants
    # surfaced inline).
    MESSAGE = "message"


class Event(BaseModel):
    """One immutable thing-that-happened.

    `seq` is monotonic *per emitter*, so a consumer can order an emitter's
    events even if delivery is async/interleaved with other sources.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    source: str
    seq: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


# --- sinks -------------------------------------------------------------

class EventSink(ABC):
    """Where events go. Implementations must be cheap and non-blocking:
    `emit` is called synchronously from inside tool execution."""

    @abstractmethod
    def emit(self, event: Event) -> None: ...


class NullSink(EventSink):
    """Drops every event. The default, so emitting is always safe."""

    def emit(self, event: Event) -> None:  # noqa: D401
        return None


class CallbackSink(EventSink):
    """Forwards each event to a plain callable."""

    def __init__(self, callback: Callable[[Event], None]) -> None:
        self._callback = callback

    def emit(self, event: Event) -> None:
        self._callback(event)


class CollectingSink(EventSink):
    """Appends events to an in-memory list. Handy for tests and buffering."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]


class QueueSink(EventSink):
    """Pushes events onto a queue with ``put_nowait`` — the streaming path.

    Works with any object exposing ``put_nowait`` (``asyncio.Queue``,
    ``queue.Queue``). A websocket/SSE handler drains the queue and streams
    events to the browser while the agent runs. Non-blocking by contract; if
    the queue is full the underlying ``put_nowait`` raises and the caller
    decides — emitting never blocks tool execution on a slow consumer.
    """

    def __init__(self, queue: Any) -> None:
        self._queue = queue

    def emit(self, event: Event) -> None:
        self._queue.put_nowait(event)


def as_sink(sink: EventSink | Callable[[Event], None] | None) -> EventSink:
    """Coerce ``None``/a callable/a sink into an :class:`EventSink`."""
    if sink is None:
        return NullSink()
    if isinstance(sink, EventSink):
        return sink
    if callable(sink):
        return CallbackSink(sink)
    raise TypeError(f"expected an EventSink, callable, or None; got {type(sink)!r}")


# --- emitter -----------------------------------------------------------

class EventEmitter:
    """Produces events for one ``source`` into one sink.

    Cheap to construct and to drop into a tool runner. With a ``NullSink``
    (the default when no sink is configured) every method is a no-op beyond a
    counter bump, so callers never need to branch on "is eventing enabled".
    """

    def __init__(
        self,
        sink: EventSink | Callable[[Event], None] | None = None,
        *,
        source: str = "",
        base_payload: dict[str, Any] | None = None,
    ) -> None:
        self._sink = as_sink(sink)
        self._source = source
        self._seq = 0
        self._base = dict(base_payload or {})

    @property
    def source(self) -> str:
        return self._source

    def emit(self, kind: str, **payload: Any) -> Event:
        event = Event(
            kind=kind,
            source=self._source,
            seq=self._seq,
            payload={**self._base, **payload},
        )
        self._seq += 1
        self._sink.emit(event)
        return event

    def child(self, source: str, **base_payload: Any) -> "EventEmitter":
        """A nested emitter sharing this sink — for a subagent dispatched by a
        tool. Carries ``parent`` so the consumer can rebuild the tree."""
        merged = {**self._base, "parent": self._source, **base_payload}
        return EventEmitter(self._sink, source=source, base_payload=merged)

    # -- conveniences ---------------------------------------------------
    def tool_start(self, **payload: Any) -> Event:
        return self.emit(EventKind.TOOL_START, **payload)

    def tool_end(self, **payload: Any) -> Event:
        return self.emit(EventKind.TOOL_END, **payload)

    def tool_error(self, error: str, **payload: Any) -> Event:
        return self.emit(EventKind.TOOL_ERROR, error=error, **payload)

    def progress(
        self,
        message: str | None = None,
        *,
        current: int | None = None,
        total: int | None = None,
        **payload: Any,
    ) -> Event:
        if message is not None:
            payload["message"] = message
        if current is not None:
            payload["current"] = current
        if total is not None:
            payload["total"] = total
        return self.emit(EventKind.PROGRESS, **payload)

    def message(self, text: str, **payload: Any) -> Event:
        return self.emit(EventKind.MESSAGE, text=text, **payload)


# --- runner integration -----------------------------------------------

def runner_accepts_emitter(runner: Callable[..., Any]) -> bool:
    """True if ``runner`` can take an :class:`EventEmitter` as a 3rd argument.

    Lets a tool/subagent runner opt into mid-run progress simply by widening
    its signature from ``(name, args)`` to ``(name, args, emitter)`` — no
    marker, no registration. Anything we cannot introspect is treated as the
    2-arg form (safe default).
    """
    try:
        sig = inspect.signature(runner)
    except (TypeError, ValueError):  # builtins, C callables
        return False
    positional = 0
    for p in sig.parameters.values():
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            return True
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional += 1
    return positional >= 3


def invoke_runner(
    runner: Callable[..., str],
    name: str,
    args: dict[str, Any],
    emitter: EventEmitter | None = None,
) -> str:
    """Call ``runner``, passing ``emitter`` only if it accepts one."""
    if emitter is not None and runner_accepts_emitter(runner):
        return runner(name, args, emitter)
    return runner(name, args)


__all__ = [
    "Event",
    "EventKind",
    "EventSink",
    "NullSink",
    "CallbackSink",
    "CollectingSink",
    "QueueSink",
    "as_sink",
    "EventEmitter",
    "runner_accepts_emitter",
    "invoke_runner",
]
