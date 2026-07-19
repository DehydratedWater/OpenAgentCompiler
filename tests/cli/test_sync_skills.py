"""`oac sync-skills` end-to-end + drift detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.cli.main import main as cli_main
from open_agent_compiler.skills import check_drift, list_skills


def _init(target: Path) -> None:
    cli_main([
        "init", str(target),
        "--name", "demo", "--template", "barebones",
        "--skills", "opencode,claude",
    ])


def test_sync_after_init_reports_everything_fresh(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "proj"
    _init(target)
    capsys.readouterr()

    rc = cli_main(["sync-skills", str(target), "--check"])
    out = capsys.readouterr().out
    assert rc == 0
    # Every line should report OK / fresh.
    assert "STALE" not in out
    assert "MISS" not in out
    assert "OK" in out


def test_check_detects_stale_when_sidecar_diverges(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "proj"
    _init(target)
    capsys.readouterr()
    # Tamper with one sidecar.
    sidecar = (
        target / ".opencode" / "skills" / "getting-started" / ".skill_version"
    )
    sidecar.write_text("not-the-real-hash")

    rc = cli_main(["sync-skills", str(target), "--check", "--skills", "opencode"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "STALE" in out
    assert "getting-started" in out


def test_check_detects_missing_when_skill_dir_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "proj"
    _init(target)
    capsys.readouterr()
    # Remove an entire skill directory.
    import shutil
    shutil.rmtree(target / ".opencode" / "skills" / "writing-tests")

    rc = cli_main(["sync-skills", str(target), "--check", "--skills", "opencode"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "MISS" in out
    assert "writing-tests" in out


def test_sync_rewrites_stale_sidecars(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "proj"
    _init(target)
    capsys.readouterr()
    sidecar = (
        target / ".opencode" / "skills" / "getting-started" / ".skill_version"
    )
    sidecar.write_text("stale")

    rc = cli_main(["sync-skills", str(target), "--skills", "opencode"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "wrote" in out

    # Sidecar restored to the real hash.
    bundles = {b.name: b for b in list_skills()}
    assert sidecar.read_text() == bundles["getting-started"].content_hash


def test_sync_idempotent_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "proj"
    _init(target)
    capsys.readouterr()
    rc = cli_main(["sync-skills", str(target), "--skills", "opencode"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "already up to date" in out or "wrote 0 file" in out


def test_sync_force_rewrites_even_when_fresh(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "proj"
    _init(target)
    capsys.readouterr()
    rc = cli_main([
        "sync-skills", str(target), "--skills", "opencode", "--force",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    # Force ⇒ at least one write reported.
    assert "wrote" in out


def test_sync_rejects_unknown_dialect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "proj"
    _init(target)
    capsys.readouterr()
    rc = cli_main(["sync-skills", str(target), "--skills", "bogus"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown skill dialects" in err


def test_sync_rejects_missing_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli_main(["sync-skills", str(tmp_path / "nope")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not an existing directory" in err


# ---- pure check_drift helper -------------------------------------------


def test_check_drift_returns_fresh_for_clean_install(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    _init(target)
    reports = check_drift(list_skills(), target, "opencode")
    assert all(r.status == "fresh" for r in reports)
    assert any(r.skill_name == "getting-started" for r in reports)


# ---- pi / codex drift check ---------------------------------------------


@pytest.mark.parametrize("dialect", ["pi", "codex"])
def test_check_drift_covers_pi_and_codex(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], dialect: str,
) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    # Nothing deployed yet — every bundle reports missing.
    reports = check_drift(list_skills(), target, dialect)
    assert reports and all(r.status == "missing" for r in reports)

    cli_main(["sync-skills", str(target), "--skills", dialect])
    capsys.readouterr()
    rc = cli_main(["sync-skills", str(target), "--check", "--skills", dialect])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out and "MISS" not in out and "STALE" not in out

    sidecar = next((target / f".{dialect}" / "skills").glob("*/.skill_version"))
    sidecar.write_text("not-the-real-hash")
    rc = cli_main(["sync-skills", str(target), "--check", "--skills", dialect])
    out = capsys.readouterr().out
    assert rc == 1
    assert "STALE" in out


def test_check_drift_rejects_unknown_dialect(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown skill dialect"):
        check_drift(list_skills(), tmp_path, "cursor")
