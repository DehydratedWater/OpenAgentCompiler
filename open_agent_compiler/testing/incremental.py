"""Incremental runner: skip tests whose composite hash already passed.

Read past JSONL artifacts, build a {(test_name, composite_hash) → latest
passing TestArtifact} index, and use it to decide whether a candidate
test can be skipped this round. A force-rerun flag bypasses the index.

Composite hashes are computed by Phase 5.5's artifact module; they cover
agent_state + model + mock_set + access_profile + variant. Any change to
any of those re-runs the test naturally.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.testing.artifact import TestArtifact, read_artifacts


class GreenIndex(BaseModel):
    """Lookup over the latest passing artifact per (test_name, composite_hash)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    by_key: dict[tuple[str, str], TestArtifact] = Field(default_factory=dict)

    @classmethod
    def from_artifacts(cls, artifacts: Iterable[TestArtifact]) -> "GreenIndex":
        index: dict[tuple[str, str], TestArtifact] = {}
        for art in artifacts:
            if not art.passed:
                continue
            key = (art.test_name, art.composite_hash)
            prev = index.get(key)
            if prev is None or art.timestamp >= prev.timestamp:
                index[key] = art
        return cls(by_key=index)

    @classmethod
    def from_jsonl(cls, path: Path) -> "GreenIndex":
        return cls.from_artifacts(read_artifacts(path))

    def should_skip(self, test_name: str, composite_hash: str) -> bool:
        return (test_name, composite_hash) in self.by_key

    def last_pass(self, test_name: str, composite_hash: str) -> TestArtifact | None:
        return self.by_key.get((test_name, composite_hash))


class IncrementalDecision(BaseModel):
    """The result of consulting the index for one candidate test."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    test_name: str
    composite_hash: str
    skip: bool
    reason: str = ""
    matched_artifact: TestArtifact | None = None


def decide(
    *,
    test_name: str,
    composite_hash: str,
    index: GreenIndex,
    force: bool = False,
) -> IncrementalDecision:
    """Decide whether to run or skip a test based on the green index."""
    if force:
        return IncrementalDecision(
            test_name=test_name, composite_hash=composite_hash,
            skip=False, reason="force flag set",
        )
    matched = index.last_pass(test_name, composite_hash)
    if matched is None:
        return IncrementalDecision(
            test_name=test_name, composite_hash=composite_hash,
            skip=False, reason="no prior green run for this composite",
        )
    return IncrementalDecision(
        test_name=test_name, composite_hash=composite_hash,
        skip=True,
        reason=f"matches green run from {matched.timestamp}",
        matched_artifact=matched,
    )
