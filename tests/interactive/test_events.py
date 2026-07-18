"""Event sink / emitter — runtime-agnostic, no LangChain needed.

Covers the standalone surface used by deterministic workflows and shared by
the LangChain binding: sinks, the emitter's seq/payload/conveniences, nested
subagent emitters, and the runner-arity detection that lets a runner opt into
mid-run progress.
"""

from __future__ import annotations

import pytest

from open_agent_compiler.interactive.events import (
    CallbackSink,
    CollectingSink,
    Event,
    EventEmitter,
    EventKind,
    NullSink,
    QueueSink,
    as_sink,
    invoke_runner,
    runner_accepts_emitter,
)


def test_null_sink_is_the_safe_default():
    em = EventEmitter()  # no sink
    ev = em.emit("anything", x=1)
    assert isinstance(ev, Event) and ev.kind == "anything"  # no raise, returns the event


def test_emitter_stamps_monotonic_seq_and_merges_base_payload():
    sink = CollectingSink()
    em = EventEmitter(sink, source="wf", base_payload={"job": 7})
    em.progress("step 1", current=1, total=3)
    em.progress("step 2", current=2, total=3)
    assert [e.seq for e in sink.events] == [0, 1]
    assert all(e.source == "wf" for e in sink.events)
    first = sink.events[0]
    assert first.kind == EventKind.PROGRESS
    assert first.payload == {"job": 7, "message": "step 1", "current": 1, "total": 3}


def test_tool_conveniences_use_well_known_kinds():
    sink = CollectingSink()
    em = EventEmitter(sink, source="priority-manager")
    em.tool_start(args={"input": "audit"})
    em.tool_end(result="ok")
    em.tool_error("boom")
    assert sink.kinds() == [
        EventKind.TOOL_START, EventKind.TOOL_END, EventKind.TOOL_ERROR,
    ]
    assert sink.events[2].payload == {"error": "boom"}


def test_child_emitter_shares_sink_and_records_parent():
    # A subagent dispatched by a tool: same stream, own source + seq, parent set.
    sink = CollectingSink()
    parent = EventEmitter(sink, source="dispatch", base_payload={"job": 1})
    child = parent.child("subagent-research", role="researcher")
    child.progress("thinking")
    ev = sink.events[0]
    assert ev.source == "subagent-research" and ev.seq == 0
    assert ev.payload["parent"] == "dispatch"
    assert ev.payload["job"] == 1 and ev.payload["role"] == "researcher"


def test_callback_sink_and_as_sink_coercion():
    seen: list[Event] = []
    # a bare callable should coerce to a CallbackSink
    em = EventEmitter(seen.append, source="s")
    em.message("hi")
    assert seen and seen[0].kind == EventKind.MESSAGE and seen[0].payload["text"] == "hi"
    assert isinstance(as_sink(seen.append), CallbackSink)
    assert isinstance(as_sink(None), NullSink)
    with pytest.raises(TypeError):
        as_sink(123)  # not a sink/callable/None


def test_queue_sink_uses_put_nowait():
    import queue

    q: queue.Queue = queue.Queue()
    em = EventEmitter(QueueSink(q), source="s")
    em.progress("p")
    got = q.get_nowait()
    assert got.kind == EventKind.PROGRESS and got.payload["message"] == "p"


def test_event_is_frozen():
    ev = Event(kind="k", source="s")
    with pytest.raises(Exception):
        ev.kind = "other"  # frozen


# --- runner arity detection -------------------------------------------

def test_runner_accepts_emitter_detects_three_arg_and_varargs():
    assert runner_accepts_emitter(lambda n, a: "x") is False
    assert runner_accepts_emitter(lambda n, a, em: "x") is True
    assert runner_accepts_emitter(lambda *a: "x") is True
    # builtins / uninspectable callables → safe default False
    assert runner_accepts_emitter(len) is False


def test_invoke_runner_passes_emitter_only_when_accepted():
    sink = CollectingSink()
    em = EventEmitter(sink, source="t")

    def three_arg(name, args, emitter):
        emitter.progress("halfway")
        return f"{name}:{args['input']}"

    def two_arg(name, args):
        return "no-emitter"

    assert invoke_runner(three_arg, "t", {"input": "go"}, em) == "t:go"
    assert sink.kinds() == [EventKind.PROGRESS]  # the runner emitted progress
    assert invoke_runner(two_arg, "t", {"input": "go"}, em) == "no-emitter"
