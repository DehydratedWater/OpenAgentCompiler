"""JSONL artifact emitter + hashing utilities."""

from __future__ import annotations

import json
from pathlib import Path

from open_agent_compiler.model.core.mock_model import MockResponse
from open_agent_compiler.testing.artifact import (
    ArtifactWriter,
    EvidenceEntry,
    TestArtifact,
    compute_composite_hash,
    evidence_from_results,
    mock_set_hash_from_profile_responses,
    read_artifacts,
    stable_sha256,
)
from open_agent_compiler.testing.evaluation import EvaluationResult


# ---- stable_sha256 -------------------------------------------------------


def test_stable_sha256_is_order_independent_for_dicts() -> None:
    a = stable_sha256({"x": 1, "y": 2})
    b = stable_sha256({"y": 2, "x": 1})
    assert a == b


def test_stable_sha256_distinguishes_different_payloads() -> None:
    assert stable_sha256({"a": 1}) != stable_sha256({"a": 2})


def test_stable_sha256_accepts_pydantic_models() -> None:
    a = MockResponse(kind="fixed", fixed_output={"k": "v"})
    h1 = stable_sha256(a)
    h2 = stable_sha256(a.model_copy())
    assert h1 == h2


# ---- composite hash ------------------------------------------------------


def test_composite_hash_changes_with_any_input() -> None:
    base = dict(
        agent_state_hash="A", model="m", mock_set_hash="M",
        access_profile="prod", variant="default",
    )
    h0 = compute_composite_hash(**base)
    assert h0 != compute_composite_hash(**{**base, "model": "m2"})
    assert h0 != compute_composite_hash(**{**base, "variant": "v2"})
    assert h0 != compute_composite_hash(**{**base, "access_profile": "ci"})


def test_mock_set_hash_for_no_mocks_is_stable() -> None:
    h1 = mock_set_hash_from_profile_responses({})
    h2 = mock_set_hash_from_profile_responses(None)
    assert h1 == h2


def test_mock_set_hash_changes_with_responses() -> None:
    h1 = mock_set_hash_from_profile_responses({})
    h2 = mock_set_hash_from_profile_responses({
        "echo": MockResponse(kind="fixed", fixed_output={"x": 1}),
    })
    assert h1 != h2


# ---- evidence flattening -------------------------------------------------


def test_evidence_from_results_flattens_evaluation_results() -> None:
    results = [
        EvaluationResult(
            evaluator_kind="equals", passed=True, score=1.0,
            evidence="ok", evaluator_name="exact",
        ),
        EvaluationResult(
            evaluator_kind="llm_judge", passed=False, score=0.2,
            skipped=True, skip_reason="no judge",
            evidence="skipped: no judge",
        ),
    ]
    out = evidence_from_results(results)
    assert len(out) == 2
    assert isinstance(out[0], EvidenceEntry)
    assert out[0].name == "exact"
    assert out[1].skipped is True


# ---- TestArtifact.build --------------------------------------------------


def test_artifact_build_populates_composite_hash() -> None:
    art = TestArtifact.build(
        test_kind="tool",
        test_name="happy",
        target_name="echo",
        passed=True,
        score=1.0,
        duration_s=0.001,
        agent_state_hash="A",
        mock_set_hash="M",
        evidence=[],
        variant="v1",
        access_profile="prod",
        model="m",
    )
    expected = compute_composite_hash(
        agent_state_hash="A", model="m", mock_set_hash="M",
        access_profile="prod", variant="v1",
    )
    assert art.composite_hash == expected


def test_artifact_build_uses_supplied_timestamp() -> None:
    art = TestArtifact.build(
        test_kind="capability", test_name="t", target_name="orch",
        passed=True, score=1.0, duration_s=0.0,
        agent_state_hash="A", mock_set_hash="M",
        evidence=[],
        timestamp="2026-05-17T12:00:00",
    )
    assert art.timestamp == "2026-05-17T12:00:00"


# ---- ArtifactWriter / read_artifacts -------------------------------------


def test_writer_appends_one_line_per_record(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    art1 = TestArtifact.build(
        test_kind="tool", test_name="a", target_name="t",
        passed=True, score=1.0, duration_s=0.0,
        agent_state_hash="A", mock_set_hash="M", evidence=[],
    )
    art2 = TestArtifact.build(
        test_kind="tool", test_name="b", target_name="t",
        passed=False, score=0.0, duration_s=0.0,
        agent_state_hash="A", mock_set_hash="M", evidence=[],
    )
    with ArtifactWriter(path) as w:
        w.write(art1)
        w.write(art2)
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["test_name"] == "a"
    assert json.loads(lines[1])["test_name"] == "b"


def test_writer_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "deeper" / "results.jsonl"
    art = TestArtifact.build(
        test_kind="tool", test_name="a", target_name="t",
        passed=True, score=1.0, duration_s=0.0,
        agent_state_hash="A", mock_set_hash="M", evidence=[],
    )
    with ArtifactWriter(path) as w:
        w.write(art)
    assert path.exists()


def test_writer_appends_across_invocations(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    art = TestArtifact.build(
        test_kind="tool", test_name="a", target_name="t",
        passed=True, score=1.0, duration_s=0.0,
        agent_state_hash="A", mock_set_hash="M", evidence=[],
    )
    with ArtifactWriter(path) as w:
        w.write(art)
    with ArtifactWriter(path) as w:
        w.write(art)
    assert len(path.read_text().strip().splitlines()) == 2


def test_writer_requires_context_manager(tmp_path: Path) -> None:
    import pytest as _pytest
    w = ArtifactWriter(tmp_path / "r.jsonl")
    art = TestArtifact.build(
        test_kind="tool", test_name="a", target_name="t",
        passed=True, score=1.0, duration_s=0.0,
        agent_state_hash="A", mock_set_hash="M", evidence=[],
    )
    with _pytest.raises(RuntimeError, match="context manager"):
        w.write(art)


def test_read_artifacts_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    arts = [
        TestArtifact.build(
            test_kind="capability", test_name=f"t{i}", target_name="orch",
            passed=(i % 2 == 0), score=float(i),
            duration_s=0.0,
            agent_state_hash="A", mock_set_hash="M", evidence=[],
        )
        for i in range(3)
    ]
    with ArtifactWriter(path) as w:
        for a in arts:
            w.write(a)
    parsed = read_artifacts(path)
    assert [a.test_name for a in parsed] == ["t0", "t1", "t2"]
    assert parsed[0].passed and not parsed[1].passed


def test_read_artifacts_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_artifacts(tmp_path / "does-not-exist.jsonl") == []


def test_read_artifacts_ignores_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    art = TestArtifact.build(
        test_kind="tool", test_name="a", target_name="t",
        passed=True, score=1.0, duration_s=0.0,
        agent_state_hash="A", mock_set_hash="M", evidence=[],
    )
    with ArtifactWriter(path) as w:
        w.write(art)
    # Append a blank line + another record.
    with path.open("a") as f:
        f.write("\n")
        f.write(art.model_dump_json() + "\n")
    parsed = read_artifacts(path)
    assert len(parsed) == 2
