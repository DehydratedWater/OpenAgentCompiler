"""Incremental runner: GreenIndex + decide() skip logic."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.testing.artifact import ArtifactWriter, TestArtifact
from open_agent_compiler.testing.incremental import GreenIndex, decide


def _art(
    *, name: str, composite_hash: str, passed: bool = True,
    timestamp: str = "2026-05-17T12:00:00",
) -> TestArtifact:
    return TestArtifact.build(
        test_kind="tool", test_name=name, target_name="t",
        passed=passed, score=1.0 if passed else 0.0, duration_s=0.0,
        agent_state_hash="A", mock_set_hash="M",
        evidence=[], timestamp=timestamp,
    ).model_copy(update={"composite_hash": composite_hash})


def test_index_only_keeps_passing_runs() -> None:
    idx = GreenIndex.from_artifacts([
        _art(name="a", composite_hash="h1", passed=True),
        _art(name="b", composite_hash="h2", passed=False),
    ])
    assert idx.should_skip("a", "h1")
    assert not idx.should_skip("b", "h2")


def test_index_keeps_most_recent_for_same_key() -> None:
    older = _art(name="a", composite_hash="h", timestamp="2026-05-17T08:00:00")
    newer = _art(name="a", composite_hash="h", timestamp="2026-05-17T12:00:00")
    idx = GreenIndex.from_artifacts([older, newer])
    matched = idx.last_pass("a", "h")
    assert matched is not None
    assert matched.timestamp == "2026-05-17T12:00:00"


def test_different_composite_hashes_do_not_match() -> None:
    idx = GreenIndex.from_artifacts([_art(name="a", composite_hash="h1")])
    assert idx.should_skip("a", "h1")
    assert not idx.should_skip("a", "h2")


def test_from_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    art = _art(name="a", composite_hash="h")
    with ArtifactWriter(path) as w:
        w.write(art)
    idx = GreenIndex.from_jsonl(path)
    assert idx.should_skip("a", "h")


def test_from_jsonl_missing_file_yields_empty_index(tmp_path: Path) -> None:
    idx = GreenIndex.from_jsonl(tmp_path / "missing.jsonl")
    assert idx.by_key == {}


# ---- decide() -----------------------------------------------------------


def test_decide_skips_when_index_has_passing_match() -> None:
    idx = GreenIndex.from_artifacts([_art(name="a", composite_hash="h")])
    d = decide(test_name="a", composite_hash="h", index=idx)
    assert d.skip
    assert "matches green run" in d.reason
    assert d.matched_artifact is not None


def test_decide_runs_when_no_match() -> None:
    idx = GreenIndex.from_artifacts([])
    d = decide(test_name="a", composite_hash="h", index=idx)
    assert not d.skip
    assert "no prior green" in d.reason


def test_decide_force_bypasses_skip() -> None:
    idx = GreenIndex.from_artifacts([_art(name="a", composite_hash="h")])
    d = decide(test_name="a", composite_hash="h", index=idx, force=True)
    assert not d.skip
    assert "force" in d.reason


def test_decide_runs_when_hash_changed_from_green() -> None:
    idx = GreenIndex.from_artifacts([_art(name="a", composite_hash="OLD")])
    d = decide(test_name="a", composite_hash="NEW", index=idx)
    assert not d.skip
