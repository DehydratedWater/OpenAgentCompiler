"""Sanity check the authored skill content."""

from __future__ import annotations

import pytest

from open_agent_compiler.skills import list_skills

EXPECTED_NAMES = {
    "getting-started",
    "project-orchestration",
    "authoring-agents",
    "authoring-tools",
    "tool-variants",
    "prompt-structure",
    "writing-tests",
    "providers-and-models",
    "variants-and-profiles",
    "docker-and-compose",
    "improvement-loop",
    "optimization-targets",
    "autoloop-interview",
    "sandboxed-scripting",
    "dynamic-extractor",
    "interactive-agents",
}


@pytest.fixture(scope="module")
def skills():
    return list_skills()


def test_all_expected_skills_present(skills) -> None:
    names = {s.name for s in skills}
    assert names == EXPECTED_NAMES


def test_every_skill_has_substantial_body(skills) -> None:
    for s in skills:
        # 500 bytes is a floor — these are explanatory docs, not stubs.
        assert len(s.body_markdown) > 500, (
            f"skill {s.name!r} body is too short: {len(s.body_markdown)} bytes"
        )


def test_every_skill_targets_both_dialects_by_default(skills) -> None:
    for s in skills:
        assert "opencode" in s.targets
        assert "claude" in s.targets


def test_every_skill_has_non_empty_description(skills) -> None:
    for s in skills:
        assert s.description.strip()


def test_no_duplicate_skill_names(skills) -> None:
    names = [s.name for s in skills]
    assert len(names) == len(set(names))


def test_skill_content_hashes_are_unique(skills) -> None:
    hashes = [s.content_hash for s in skills]
    assert len(hashes) == len(set(hashes))


def test_skill_bodies_render_a_top_level_heading(skills) -> None:
    for s in skills:
        first_line = s.body_markdown.lstrip().splitlines()[0]
        assert first_line.startswith("# "), (
            f"skill {s.name!r} body should start with a top-level heading,"
            f" got: {first_line!r}"
        )
