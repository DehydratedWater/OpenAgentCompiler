"""SkillBundle + emitters + registry."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.skills import (
    SkillBundle,
    emit_claude,
    emit_opencode,
    get_skill,
    list_skills,
)


def _bundle(**kw) -> SkillBundle:
    defaults = dict(
        name="demo",
        description="demo skill",
        body_markdown="# Demo\n\nbody",
    )
    defaults.update(kw)
    return SkillBundle(**defaults)


# ---- bundle -------------------------------------------------------------


def test_content_hash_changes_when_body_changes() -> None:
    a = _bundle()
    b = _bundle(body_markdown="# Demo\n\nbody updated")
    assert a.content_hash != b.content_hash


def test_content_hash_changes_when_version_changes() -> None:
    a = _bundle()
    b = _bundle(version="2.0.0")
    assert a.content_hash != b.content_hash


def test_content_hash_stable_for_identical_input() -> None:
    assert _bundle().content_hash == _bundle().content_hash


# ---- registry -----------------------------------------------------------


def test_list_skills_returns_at_least_getting_started() -> None:
    names = {s.name for s in list_skills()}
    assert "getting-started" in names


def test_get_skill_resolves_by_name() -> None:
    bundle = get_skill("getting-started")
    assert bundle is not None
    assert bundle.description


def test_get_skill_returns_none_for_unknown() -> None:
    assert get_skill("does-not-exist") is None


# ---- opencode emitter ---------------------------------------------------


def test_emit_opencode_writes_skill_md_and_sidecar(tmp_path: Path) -> None:
    bundles = [_bundle(targets=("opencode",))]
    result = emit_opencode(bundles, tmp_path)
    skill_md = tmp_path / ".opencode" / "skills" / "demo" / "SKILL.md"
    sidecar = tmp_path / ".opencode" / "skills" / "demo" / ".skill_version"
    assert skill_md.exists()
    assert sidecar.exists()
    assert sidecar.read_text() == bundles[0].content_hash
    body = skill_md.read_text()
    assert body.startswith("---\n")
    assert "name: demo" in body
    assert "# Demo" in body
    assert len(result.written) == 2


def test_emit_opencode_skips_when_sidecar_matches(tmp_path: Path) -> None:
    bundles = [_bundle(targets=("opencode",))]
    emit_opencode(bundles, tmp_path)  # first run
    result = emit_opencode(bundles, tmp_path)  # idempotent
    assert result.written == []
    assert len(result.skipped_up_to_date) >= 1


def test_emit_opencode_force_overwrites_even_when_matching(tmp_path: Path) -> None:
    bundles = [_bundle(targets=("opencode",))]
    emit_opencode(bundles, tmp_path)
    result = emit_opencode(bundles, tmp_path, force=True)
    assert result.written  # rewritten despite matching sidecar


def test_emit_opencode_skips_claude_only_bundles(tmp_path: Path) -> None:
    bundles = [_bundle(targets=("claude",))]
    result = emit_opencode(bundles, tmp_path)
    assert result.written == []


# ---- claude emitter -----------------------------------------------------


def test_emit_claude_writes_skill_and_aggregate_index(tmp_path: Path) -> None:
    bundles = [
        _bundle(name="a", description="A skill", targets=("claude",)),
        _bundle(name="b", description="B skill", targets=("claude",)),
    ]
    result = emit_claude(bundles, tmp_path)
    assert (tmp_path / ".claude" / "skills" / "a" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "skills" / "b" / "SKILL.md").exists()
    index = tmp_path / "CLAUDE.md"
    assert index.exists()
    body = index.read_text()
    assert "**a** (v1.0.0) — A skill" in body
    assert "**b** (v1.0.0) — B skill" in body


def test_emit_claude_index_excludes_opencode_only(tmp_path: Path) -> None:
    bundles = [
        _bundle(name="opc-only", targets=("opencode",)),
        _bundle(name="both", targets=("opencode", "claude")),
    ]
    emit_claude(bundles, tmp_path)
    index = (tmp_path / "CLAUDE.md").read_text()
    assert "opc-only" not in index
    assert "both" in index


def test_real_getting_started_skill_round_trips(tmp_path: Path) -> None:
    bundles = list_skills()
    emit_opencode(bundles, tmp_path)
    emit_claude(bundles, tmp_path)
    assert (tmp_path / ".opencode" / "skills" / "getting-started" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "skills" / "getting-started" / "SKILL.md").exists()
    assert (tmp_path / "CLAUDE.md").exists()
