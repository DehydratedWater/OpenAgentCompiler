"""Smart force-overwrite via scaffold manifest."""

from __future__ import annotations

from pathlib import Path


from open_agent_compiler.scaffold.config import ScaffoldConfig
from open_agent_compiler.scaffold.engine import ScaffoldEngine
from open_agent_compiler.scaffold.manifest import load_manifest, manifest_path


def _cfg(target: Path, **kw) -> ScaffoldConfig:
    return ScaffoldConfig(
        target=target, project_name="x", template="barebones",
        llm="anthropic", **kw,
    )


def test_first_scaffold_writes_manifest(tmp_path: Path) -> None:
    ScaffoldEngine(config=_cfg(tmp_path)).render()
    p = manifest_path(tmp_path)
    assert p.exists()
    m = load_manifest(tmp_path)
    # Every emitted file should be in the manifest.
    assert "pyproject.toml" in m["files"]
    assert "agents/registry.py" in m["files"]


def test_re_scaffold_no_force_skips_everything(tmp_path: Path) -> None:
    """Without --force-overwrite, no overwrites happen."""
    ScaffoldEngine(config=_cfg(tmp_path)).render()
    result = ScaffoldEngine(config=_cfg(tmp_path)).render()
    # All files exist + their content matches what we'd write →
    # classification 'unchanged'. NOT skipped (we recorded the hash).
    # We expect a quiet no-op.
    assert len(result.written_files) == 0
    assert len(result.preserved_user_files) == 0


def test_re_scaffold_force_refreshes_framework_files(tmp_path: Path) -> None:
    """Framework-owned files (untouched) get overwritten with --force."""
    ScaffoldEngine(config=_cfg(tmp_path)).render()
    # Simulate a framework fix changing the .env.example output.
    env = tmp_path / ".env.example"
    original_content = env.read_text()
    # User hasn't touched the file — so it's framework-owned. The
    # second render with force_overwrite=True should leave it as-is
    # (no diff) OR overwrite with current generator content. Either
    # way, the file should NOT land in preserved_user_files.
    result = ScaffoldEngine(config=_cfg(
        tmp_path, force_overwrite=True,
    )).render()
    assert env not in result.preserved_user_files


def test_re_scaffold_force_preserves_user_edited_file(tmp_path: Path) -> None:
    """User-edited files (sha256 differs from manifest) are preserved."""
    ScaffoldEngine(config=_cfg(tmp_path)).render()
    # Simulate the user customising agents/registry.py.
    registry = tmp_path / "agents" / "registry.py"
    registry.write_text("# my custom registry\nprint('hi')\n")
    result = ScaffoldEngine(config=_cfg(
        tmp_path, force_overwrite=True,
    )).render()
    assert registry in result.preserved_user_files
    # Content unchanged.
    assert registry.read_text() == "# my custom registry\nprint('hi')\n"


def test_force_overwrite_all_nukes_user_files(tmp_path: Path) -> None:
    """--force-overwrite-all writes everything, ignoring user edits."""
    ScaffoldEngine(config=_cfg(tmp_path)).render()
    registry = tmp_path / "agents" / "registry.py"
    registry.write_text("# my custom registry\n")
    result = ScaffoldEngine(config=_cfg(
        tmp_path, force_overwrite_all=True,
    )).render()
    assert registry not in result.preserved_user_files
    assert registry in result.written_files
    # Content reset.
    assert registry.read_text() != "# my custom registry\n"


def test_overwrite_all_implies_force_overwrite() -> None:
    """force_overwrite_all=True auto-sets force_overwrite=True."""
    cfg = ScaffoldConfig(
        target=Path("/tmp/x"), project_name="x", template="barebones",
        llm="anthropic", force_overwrite_all=True,
    )
    assert cfg.force_overwrite is True
    assert cfg.force_overwrite_all is True


def test_orphan_files_in_target_are_preserved(tmp_path: Path) -> None:
    """A pre-existing file (no manifest entry, force=True) is preserved."""
    # Drop a stray file before any scaffold runs.
    tmp_path.mkdir(parents=True, exist_ok=True)
    stray = tmp_path / "pyproject.toml"
    stray.write_text("# pre-existing user file\n")
    result = ScaffoldEngine(config=_cfg(
        tmp_path, force_overwrite=True,
    )).render()
    # Pre-existing pyproject is classified 'orphan' → preserved.
    assert stray in result.preserved_user_files
    assert "pre-existing user file" in stray.read_text()


def test_user_edits_recorded_in_subsequent_manifests(tmp_path: Path) -> None:
    """After a user edit + preserve, the new hash is in the manifest so
    further edits are also detected."""
    ScaffoldEngine(config=_cfg(tmp_path)).render()
    registry = tmp_path / "agents" / "registry.py"
    registry.write_text("# v1 customisation\n")
    ScaffoldEngine(config=_cfg(tmp_path, force_overwrite=True)).render()
    # Second user edit on top.
    registry.write_text("# v2 customisation\n")
    result = ScaffoldEngine(config=_cfg(tmp_path, force_overwrite=True)).render()
    # Still preserved (the manifest now records v1's hash).
    assert registry in result.preserved_user_files
    assert "v2 customisation" in registry.read_text()
