"""Per-test JSONL artifacts + composite hashing.

Each test run emits one JSON object per line into a results file
(default .oac/test_results.jsonl). The record carries enough metadata
that Phase 5.6's incremental runner can skip tests whose inputs (agent
state, mock set, model, access profile) all match the last green run.

Composite hash recipe (sha256 of the canonical JSON of):
  {
    "agent_state_hash": ...,
    "model": ...,
    "mock_set_hash": ...,
    "access_profile": ...,
    "variant": ...,
  }

agent_state_hash uses the model_dump_json (sort_keys=True) of either:
- For agent/capability tests: the AgentDefinition.
- For tool tests: the ToolDefinition.
mock_set_hash hashes the resolved MockProfile.responses for the test,
or the empty dict when no mocks are in play.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TestKind = Literal["capability", "tool", "agent"]


def stable_sha256(payload: Any) -> str:
    """SHA-256 over the canonical JSON form of `payload`."""
    if isinstance(payload, BaseModel):
        text = payload.model_dump_json()
        # Re-load + dump with sort_keys to get a canonical form.
        canonical = json.dumps(json.loads(text), sort_keys=True, default=str)
    else:
        canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_composite_hash(
    *,
    agent_state_hash: str,
    model: str | None,
    mock_set_hash: str,
    access_profile: str | None,
    variant: str | None,
) -> str:
    return stable_sha256({
        "agent_state_hash": agent_state_hash,
        "model": model,
        "mock_set_hash": mock_set_hash,
        "access_profile": access_profile,
        "variant": variant,
    })


def mock_set_hash_from_profile_responses(
    responses: dict[str, Any] | None,
) -> str:
    """Hash a MockProfile.responses dict (or {} for no mocks)."""
    if not responses:
        return stable_sha256({})
    # Each value is a MockResponse — model_dump_json gives canonical form.
    canonical = {
        name: (
            mr.model_dump() if isinstance(mr, BaseModel) else mr
        )
        for name, mr in responses.items()
    }
    return stable_sha256(canonical)


class EvidenceEntry(BaseModel):
    """One evaluator's outcome flattened for the JSONL record."""

    model_config = ConfigDict(frozen=False)

    evaluator_kind: str
    name: str = ""
    passed: bool
    score: float = 0.0
    skipped: bool = False
    evidence: str = ""


class TestArtifact(BaseModel):
    """A single line in the JSONL results file."""

    # Tell pytest this isn't a test class — its name starts with "Test"
    # which would otherwise trigger collection.
    __test__ = False

    model_config = ConfigDict(frozen=False)

    timestamp: str
    test_kind: TestKind
    test_name: str
    target_name: str = Field(
        default="",
        description=(
            "Agent name for agent/capability tests; tool name for tool tests."
        ),
    )
    passed: bool
    score: float = 1.0
    duration_s: float = 0.0
    variant: str | None = None
    access_profile: str | None = None
    mock_profile: str | None = None
    model: str | None = None
    agent_state_hash: str
    mock_set_hash: str
    composite_hash: str
    evidence: list[EvidenceEntry] = Field(default_factory=list)
    skip_reason: str = ""

    @classmethod
    def build(
        cls,
        *,
        test_kind: TestKind,
        test_name: str,
        target_name: str,
        passed: bool,
        score: float,
        duration_s: float,
        agent_state_hash: str,
        mock_set_hash: str,
        evidence: list[EvidenceEntry],
        variant: str | None = None,
        access_profile: str | None = None,
        mock_profile: str | None = None,
        model: str | None = None,
        skip_reason: str = "",
        timestamp: str | None = None,
    ) -> "TestArtifact":
        return cls(
            timestamp=timestamp or datetime.now().isoformat(timespec="seconds"),
            test_kind=test_kind,
            test_name=test_name,
            target_name=target_name,
            passed=passed,
            score=score,
            duration_s=duration_s,
            agent_state_hash=agent_state_hash,
            mock_set_hash=mock_set_hash,
            composite_hash=compute_composite_hash(
                agent_state_hash=agent_state_hash,
                model=model,
                mock_set_hash=mock_set_hash,
                access_profile=access_profile,
                variant=variant,
            ),
            evidence=evidence,
            variant=variant,
            access_profile=access_profile,
            mock_profile=mock_profile,
            model=model,
            skip_reason=skip_reason,
        )


def evidence_from_results(results) -> list[EvidenceEntry]:
    """Convert a list of EvaluationResult to JSONL-friendly entries."""
    return [
        EvidenceEntry(
            evaluator_kind=r.evaluator_kind,
            name=r.evaluator_name,
            passed=r.passed,
            score=r.score,
            skipped=r.skipped,
            evidence=r.evidence,
        )
        for r in results
    ]


class ArtifactWriter:
    """Append-only JSONL writer for test artifacts.

    Use as a context manager to ensure the file handle is closed:

        with ArtifactWriter(Path('.oac/test_results.jsonl')) as w:
            w.write(artifact)
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None

    def __enter__(self) -> "ArtifactWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, *exc_info) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def write(self, artifact: TestArtifact) -> None:
        if self._fh is None:
            raise RuntimeError(
                "ArtifactWriter must be used as a context manager."
            )
        self._fh.write(artifact.model_dump_json() + "\n")


def read_artifacts(path: Path) -> list[TestArtifact]:
    """Parse every line of a JSONL artifacts file. Empty when missing."""
    if not path.exists():
        return []
    out: list[TestArtifact] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(TestArtifact.model_validate_json(line))
    return out
