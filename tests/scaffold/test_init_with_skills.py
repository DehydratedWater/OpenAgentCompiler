"""--skills flag wiring on `oac init`."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.cli.commands.init import _parse_skills
from open_agent_compiler.cli.main import main as cli_main
from open_agent_compiler.scaffold.config import ScaffoldConfig
from open_agent_compiler.scaffold.engine import ScaffoldEngine


def test_parse_skills_empty_or_none() -> None:
    assert _parse_skills("") == ()
    assert _parse_skills("none") == ()
    assert _parse_skills("NONE") == ()


def test_parse_skills_single() -> None:
    assert _parse_skills("opencode") == ("opencode",)


def test_parse_skills_multiple() -> None:
    assert _parse_skills("opencode,claude") == ("opencode", "claude")
    assert _parse_skills(" opencode , claude ") == ("opencode", "claude")


def test_parse_skills_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown skill dialects"):
        _parse_skills("opencode,bogus")


def test_engine_no_skills_emits_no_skill_files(tmp_path: Path) -> None:
    cfg = ScaffoldConfig(target=tmp_path, project_name="proj", skills=())
    result = ScaffoldEngine(config=cfg).render()
    assert result.skill_files == []
    assert not (tmp_path / ".opencode").exists()
    assert not (tmp_path / ".claude").exists()


def test_engine_opencode_skills_emit_into_opencode_skills_dir(tmp_path: Path) -> None:
    cfg = ScaffoldConfig(
        target=tmp_path, project_name="proj", skills=("opencode",),
    )
    result = ScaffoldEngine(config=cfg).render()
    assert result.skill_files
    assert (tmp_path / ".opencode" / "skills" / "getting-started" / "SKILL.md").exists()
    # Claude tree NOT emitted when only opencode requested.
    assert not (tmp_path / ".claude").exists()


def test_engine_claude_skills_emit_claude_md_index(tmp_path: Path) -> None:
    cfg = ScaffoldConfig(
        target=tmp_path, project_name="proj", skills=("claude",),
    )
    ScaffoldEngine(config=cfg).render()
    assert (tmp_path / ".claude" / "skills" / "getting-started" / "SKILL.md").exists()
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    body = claude_md.read_text()
    assert "getting-started" in body


def test_engine_both_skills_emit_both_trees(tmp_path: Path) -> None:
    cfg = ScaffoldConfig(
        target=tmp_path, project_name="proj",
        skills=("opencode", "claude"),
    )
    ScaffoldEngine(config=cfg).render()
    assert (tmp_path / ".opencode" / "skills" / "getting-started" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "skills" / "getting-started" / "SKILL.md").exists()
    assert (tmp_path / "CLAUDE.md").exists()


def test_cli_init_with_skills_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "proj"
    rc = cli_main([
        "init", str(target),
        "--name", "demo",
        "--template", "barebones",
        "--skills", "opencode,claude",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "skill file" in out
    assert (target / ".opencode" / "skills" / "getting-started" / "SKILL.md").exists()
    assert (target / "CLAUDE.md").exists()


def test_cli_init_skills_none_omits_emission(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "proj"
    rc = cli_main([
        "init", str(target),
        "--name", "demo",
        "--template", "barebones",
        "--skills", "none",
    ])
    capsys.readouterr()
    assert rc == 0
    assert not (target / ".opencode").exists()


def test_cli_init_rejects_unknown_skill_dialect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli_main([
        "init", str(tmp_path / "proj"),
        "--template", "barebones",
        "--skills", "opencode,bogus",
    ])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown skill dialects" in err
