"""ComponentVersion + ComponentRegistry: hashing, lineage, diff, metrics."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from open_agent_compiler.improvement.version import (
    ComponentRegistry,
    ComponentVersion,
    stable_content_hash,
)


def _agent_def(prompt: str = "default") -> dict:
    return {"name": "orch", "system_prompt": prompt, "subagents": []}


# ---- stable_content_hash ------------------------------------------------


def test_hash_is_stable_for_identical_dict() -> None:
    assert stable_content_hash({"a": 1, "b": 2}) == stable_content_hash({"a": 1, "b": 2})


def test_hash_order_independent() -> None:
    a = stable_content_hash({"a": 1, "b": 2})
    b = stable_content_hash({"b": 2, "a": 1})
    assert a == b


def test_hash_changes_when_content_changes() -> None:
    assert stable_content_hash({"a": 1}) != stable_content_hash({"a": 2})


def test_hash_accepts_pydantic_models() -> None:
    class M(BaseModel):
        x: int
        y: str

    h1 = stable_content_hash(M(x=1, y="hi"))
    h2 = stable_content_hash({"x": 1, "y": "hi"})
    assert h1 == h2


# ---- ComponentVersion.of -----------------------------------------------


def test_of_computes_content_hash() -> None:
    v = ComponentVersion.of("orch", "agent", _agent_def("hi"))
    assert v.content_hash == stable_content_hash(_agent_def("hi"))
    assert v.parent_hash is None
    assert v.author == "human"


def test_of_carries_parent_and_author_through() -> None:
    parent = ComponentVersion.of("orch", "agent", _agent_def("v1"))
    child = ComponentVersion.of(
        "orch", "agent", _agent_def("v2"),
        parent_hash=parent.content_hash, author="prompt-rewriter",
    )
    assert child.parent_hash == parent.content_hash
    assert child.author == "prompt-rewriter"


def test_validator_rejects_tampered_hash() -> None:
    with pytest.raises(ValueError, match="does not match"):
        ComponentVersion(
            component_id="orch", kind="agent",
            content_hash="0" * 64, definition={"x": 1},
        )


# ---- registry ----------------------------------------------------------


def test_register_then_get_round_trip() -> None:
    reg = ComponentRegistry()
    v = ComponentVersion.of("orch", "agent", _agent_def("v1"))
    reg.register(v)
    assert reg.get(v.content_hash) is v


def test_register_rejects_duplicate_content_hash() -> None:
    reg = ComponentRegistry()
    v = ComponentVersion.of("orch", "agent", _agent_def("v1"))
    reg.register(v)
    duplicate = ComponentVersion.of("orch", "agent", _agent_def("v1"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(duplicate)


def test_register_rejects_orphan_parent() -> None:
    reg = ComponentRegistry()
    orphan = ComponentVersion.of(
        "orch", "agent", _agent_def("v2"),
        parent_hash="deadbeef" * 8,
    )
    with pytest.raises(ValueError, match="not in registry"):
        reg.register(orphan)


def test_each_registry_instance_isolated() -> None:
    a = ComponentRegistry()
    b = ComponentRegistry()
    v = ComponentVersion.of("orch", "agent", _agent_def("v1"))
    a.register(v)
    # b must NOT have it (the bug we guard against in __init__).
    assert b.get(v.content_hash) is None


def test_history_is_chronological() -> None:
    reg = ComponentRegistry()
    v1 = ComponentVersion.of(
        "orch", "agent", _agent_def("v1"), timestamp="2026-05-17T08:00:00",
    )
    v2 = ComponentVersion.of(
        "orch", "agent", _agent_def("v2"),
        parent_hash=v1.content_hash, timestamp="2026-05-17T12:00:00",
    )
    # Register out of order to verify sort.
    reg.register(v1)
    reg.register(v2)
    history = reg.history("orch")
    assert [h.timestamp for h in history] == [
        "2026-05-17T08:00:00", "2026-05-17T12:00:00",
    ]


def test_ancestors_walks_parent_chain() -> None:
    reg = ComponentRegistry()
    v1 = ComponentVersion.of("orch", "agent", _agent_def("v1"))
    v2 = ComponentVersion.of(
        "orch", "agent", _agent_def("v2"), parent_hash=v1.content_hash,
    )
    v3 = ComponentVersion.of(
        "orch", "agent", _agent_def("v3"), parent_hash=v2.content_hash,
    )
    reg.register(v1)
    reg.register(v2)
    reg.register(v3)
    chain = reg.ancestors(v3.content_hash)
    assert [v.definition["system_prompt"] for v in chain] == ["v3", "v2", "v1"]


def test_by_metric_sorts_descending_by_default() -> None:
    reg = ComponentRegistry()
    v1 = ComponentVersion.of(
        "orch", "agent", _agent_def("v1"), metrics={"pass_rate": 0.5},
    )
    v2 = ComponentVersion.of(
        "orch", "agent", _agent_def("v2"),
        parent_hash=v1.content_hash, metrics={"pass_rate": 0.9},
    )
    v3 = ComponentVersion.of(
        "orch", "agent", _agent_def("v3"),
        parent_hash=v2.content_hash, metrics={"pass_rate": 0.7},
    )
    reg.register(v1); reg.register(v2); reg.register(v3)
    top = reg.by_metric("orch", "pass_rate")
    assert [v.metrics["pass_rate"] for v in top] == [0.9, 0.7, 0.5]


def test_by_metric_ascending() -> None:
    reg = ComponentRegistry()
    v1 = ComponentVersion.of("orch", "agent", _agent_def("v1"), metrics={"latency": 5.0})
    v2 = ComponentVersion.of(
        "orch", "agent", _agent_def("v2"),
        parent_hash=v1.content_hash, metrics={"latency": 2.0},
    )
    reg.register(v1); reg.register(v2)
    top = reg.by_metric("orch", "latency", descending=False)
    assert top[0].metrics["latency"] == 2.0


def test_by_metric_skips_versions_without_metric() -> None:
    reg = ComponentRegistry()
    v1 = ComponentVersion.of("orch", "agent", _agent_def("v1"), metrics={"pass_rate": 0.5})
    v2 = ComponentVersion.of(
        "orch", "agent", _agent_def("v2"),
        parent_hash=v1.content_hash,  # no metrics
    )
    reg.register(v1); reg.register(v2)
    out = reg.by_metric("orch", "pass_rate")
    assert len(out) == 1
    assert out[0].metrics["pass_rate"] == 0.5


# ---- diff --------------------------------------------------------------


def test_diff_reports_changed_keys() -> None:
    reg = ComponentRegistry()
    v1 = ComponentVersion.of("orch", "agent", _agent_def("hello"))
    v2 = ComponentVersion.of(
        "orch", "agent", _agent_def("goodbye"), parent_hash=v1.content_hash,
    )
    reg.register(v1); reg.register(v2)
    diffs = reg.diff(v1.content_hash, v2.content_hash)
    paths = [d["path"] for d in diffs]
    assert "system_prompt" in paths


def test_diff_walks_nested_dicts() -> None:
    reg = ComponentRegistry()
    a = {"x": {"y": 1, "z": 2}}
    b = {"x": {"y": 5, "z": 2}}
    v1 = ComponentVersion.of("c", "agent", a)
    v2 = ComponentVersion.of("c", "agent", b, parent_hash=v1.content_hash)
    reg.register(v1); reg.register(v2)
    diffs = reg.diff(v1.content_hash, v2.content_hash)
    assert any(d["path"] == "x.y" for d in diffs)


def test_diff_walks_lists_by_index() -> None:
    reg = ComponentRegistry()
    v1 = ComponentVersion.of("c", "agent", {"steps": ["a", "b", "c"]})
    v2 = ComponentVersion.of(
        "c", "agent", {"steps": ["a", "B", "c"]}, parent_hash=v1.content_hash,
    )
    reg.register(v1); reg.register(v2)
    diffs = reg.diff(v1.content_hash, v2.content_hash)
    assert any(d["path"] == "steps[1]" for d in diffs)
    entry = [d for d in diffs if d["path"] == "steps[1]"][0]
    assert entry["before"] == "b"
    assert entry["after"] == "B"


def test_diff_unknown_hash_raises() -> None:
    reg = ComponentRegistry()
    v = ComponentVersion.of("c", "agent", {"x": 1})
    reg.register(v)
    with pytest.raises(KeyError):
        reg.diff(v.content_hash, "ffff" * 16)
