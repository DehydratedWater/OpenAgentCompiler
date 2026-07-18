"""End-to-end orchestration: discover → decide (incremental) → run → emit.

Wires together every other module in open_agent_compiler/testing/ behind a single
TestRun.run() call that the `oac test` CLI invokes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.compiler.dialects.opencode.compile_permissions import generate_permissions
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.testing.artifact import (
    ArtifactWriter,
    TestArtifact,
    evidence_from_results,
    mock_set_hash_from_profile_responses,
    stable_sha256,
)
from open_agent_compiler.testing.discover import (
    CapabilityCandidate,
    ToolCandidate,
    discover,
)
from open_agent_compiler.testing.incremental import GreenIndex, decide
from open_agent_compiler.testing.runner.capability import run_capability_test
from open_agent_compiler.testing.runner.tool import run_tool_test


class RunSummary(BaseModel):
    model_config = ConfigDict(frozen=False)
    discovered: int = 0
    skipped: int = 0
    passed: int = 0
    failed: int = 0
    not_runnable: int = 0
    artifacts_path: Path | None = None
    failures: list[tuple[str, str]] = Field(
        default_factory=list,
        description="(test_name, short_reason) for each failure.",
    )


def _agent_state_hash(variant) -> str:
    return stable_sha256(variant.agent_definition)


def _tool_state_hash(tool) -> str:
    return stable_sha256(tool)


def _profile_lookup(registry: AgentRegistry) -> Callable[[str], object | None]:
    return registry.get_mock_profile


def _declared_tool_names(variant) -> tuple[str, ...]:
    """Tool names reachable from an agent: extra_tools + workflow step tools."""
    agent = getattr(variant, "agent_definition", None)
    if agent is None:
        return ()
    names: list[str] = []
    for t in getattr(agent, "extra_tools", []) or []:
        names.append(t.header.name)
    for step in getattr(agent, "workflow", []) or []:
        for t in getattr(step, "tools_used", []) or []:
            names.append(t.header.name)
    # de-dup, preserve order
    seen: set[str] = set()
    return tuple(n for n in names if not (n in seen or seen.add(n)))


def _capability_artifact(
    cand: CapabilityCandidate, registry: AgentRegistry, *,
    variant_name: str | None,
) -> tuple[TestArtifact, bool]:
    """Run one capability test and produce an artifact. Returns (art, passed)."""
    start = time.perf_counter()
    permissions_dict = generate_permissions(cand.variant)["permission"]
    out = run_capability_test(
        cand.test, permissions_dict,
        declared_tools=_declared_tool_names(cand.variant),
    )
    duration = time.perf_counter() - start

    art = TestArtifact.build(
        test_kind="capability",
        test_name=cand.test.name,
        target_name=cand.variant.agent_definition.header.name,
        passed=out.passed,
        score=1.0 if out.passed else 0.0,
        duration_s=duration,
        agent_state_hash=_agent_state_hash(cand.variant),
        mock_set_hash=mock_set_hash_from_profile_responses(None),
        evidence=evidence_from_results(out.results),
        variant=variant_name,
        model=cand.variant.model_parameters.model_name,
    )
    return art, out.passed


def _tool_artifact(
    cand: ToolCandidate, registry: AgentRegistry, *,
    variant_name: str | None,
) -> tuple[TestArtifact, bool]:
    start = time.perf_counter()
    out = run_tool_test(
        cand.test, cand.tool, profile_lookup=registry.get_mock_profile,
    )
    duration = time.perf_counter() - start

    profile = (
        registry.get_mock_profile(cand.test.mock_profile)
        if cand.test.mock_profile else None
    )
    mock_responses = profile.responses if profile is not None else None

    art = TestArtifact.build(
        test_kind="tool",
        test_name=cand.test.name,
        target_name=cand.tool.header.name,
        passed=out.passed,
        score=1.0 if out.passed else 0.0,
        duration_s=duration,
        agent_state_hash=_tool_state_hash(cand.tool),
        mock_set_hash=mock_set_hash_from_profile_responses(mock_responses),
        evidence=evidence_from_results(out.results),
        variant=variant_name,
        access_profile=cand.test.access_profile,
        mock_profile=cand.test.mock_profile,
        skip_reason=out.skip_reason,
    )
    return art, out.passed


class TestRun(BaseModel):
    """One invocation of the test runner."""

    __test__ = False  # not a pytest class

    model_config = ConfigDict(arbitrary_types_allowed=True)

    factory: Callable[[], AgentRegistry]
    config: str
    artifacts_path: Path = Path(".oac/test_results.jsonl")
    force: bool = False
    name_filter: str | None = None
    kind_filter: str | None = None
    variant_name: str | None = None
    verbose: bool = False

    def run(self) -> RunSummary:
        registry = self.factory()
        resolved = registry.resolve_config(self.config)
        discovered = discover(resolved)

        if self.kind_filter == "capability":
            discovered.tool = []
            discovered.agent = []
        elif self.kind_filter == "tool":
            discovered.capability = []
            discovered.agent = []
        elif self.kind_filter == "agent":
            discovered.capability = []
            discovered.tool = []

        if self.name_filter:
            f = self.name_filter
            discovered.capability = [c for c in discovered.capability if f in c.test.name]
            discovered.tool = [c for c in discovered.tool if f in c.test.name]
            discovered.agent = [c for c in discovered.agent if f in c.test.name]

        index = GreenIndex.from_jsonl(self.artifacts_path)
        summary = RunSummary(
            discovered=discovered.total(),
            artifacts_path=self.artifacts_path,
        )

        with ArtifactWriter(self.artifacts_path) as writer:
            for cand in discovered.capability:
                art, passed = _capability_artifact(
                    cand, registry, variant_name=self.variant_name,
                )
                self._apply_incremental(
                    art, summary, writer, candidate_label=cand.test.name,
                    cand_passed=passed, index=index,
                )

            for cand in discovered.tool:
                art, passed = _tool_artifact(
                    cand, registry, variant_name=self.variant_name,
                )
                self._apply_incremental(
                    art, summary, writer, candidate_label=cand.test.name,
                    cand_passed=passed, index=index,
                )

            for cand in discovered.agent:
                # AgentTests need an invoker — out of scope for this commit.
                summary.not_runnable += 1
                if self.verbose:
                    print(
                        f"  agent test {cand.test.name!r}: "
                        f"skipped (requires invoker; not yet wired)"
                    )

        return summary

    def _apply_incremental(
        self, art: TestArtifact, summary: RunSummary, writer: ArtifactWriter,
        *, candidate_label: str, cand_passed: bool, index: GreenIndex,
    ) -> None:
        decision = decide(
            test_name=art.test_name, composite_hash=art.composite_hash,
            index=index, force=self.force,
        )
        if decision.skip:
            summary.skipped += 1
            if self.verbose:
                print(f"  skip {candidate_label!r}: {decision.reason}")
            return

        writer.write(art)
        if cand_passed:
            summary.passed += 1
            if self.verbose:
                print(f"  pass {candidate_label!r}")
        else:
            summary.failed += 1
            short = next(
                (e.evidence for e in art.evidence if not e.passed),
                "no per-evaluator evidence",
            )
            summary.failures.append((candidate_label, short))
            if self.verbose:
                print(f"  FAIL {candidate_label!r}: {short}")
