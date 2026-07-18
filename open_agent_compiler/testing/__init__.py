"""Test runner + evaluators for open-agent-compiler.

The models in open_agent_compiler/model/core/test_model.py declare what tests look like.
This package implements:

- evaluation.py — EvaluationResult + RunContext + evaluate() dispatcher.
- evaluators/      — one module per evaluator family (deterministic,
                     llm_judge, permission).
- runner/          — per-test-kind runners (capability, tool, agent)
                     landing in Phase 5.3+.
"""

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
from open_agent_compiler.testing.evaluation import EvaluationResult, RunContext, evaluate
from open_agent_compiler.testing.incremental import GreenIndex, IncrementalDecision, decide
from open_agent_compiler.testing.provider_guard import (
    DEFAULT_EXCLUDE,
    RAW_PROVIDER_PATTERNS,
    Finding,
    assert_no_raw_provider_endpoints,
    scan_repo,
    scan_source,
)

__all__ = [
    "EvaluationResult",
    "RunContext",
    "evaluate",
    "Finding",
    "RAW_PROVIDER_PATTERNS",
    "DEFAULT_EXCLUDE",
    "scan_source",
    "scan_repo",
    "assert_no_raw_provider_endpoints",
    "ArtifactWriter",
    "EvidenceEntry",
    "TestArtifact",
    "compute_composite_hash",
    "evidence_from_results",
    "mock_set_hash_from_profile_responses",
    "read_artifacts",
    "stable_sha256",
    "GreenIndex",
    "IncrementalDecision",
    "decide",
]
