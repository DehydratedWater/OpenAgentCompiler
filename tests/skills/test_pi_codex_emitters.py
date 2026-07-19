"""pi + codex skill emitters — the cross-agent SKILL.md standard."""

from __future__ import annotations

from pathlib import Path

import yaml

from open_agent_compiler.skills import emit_codex, emit_pi, list_skills


def test_emit_pi_writes_skill_md_layout(tmp_path: Path) -> None:
    out = emit_pi(list_skills(), tmp_path)
    skill_md = tmp_path / ".pi" / "skills" / "autoloop-interview" / "SKILL.md"
    assert skill_md.exists()
    frontmatter = yaml.safe_load(skill_md.read_text().split("---")[1])
    assert frontmatter["name"] == "autoloop-interview"
    assert frontmatter["description"]
    assert len(out.written) >= 2 * len(list_skills())  # SKILL.md + sidecar each


def test_emit_codex_writes_skill_md_layout(tmp_path: Path) -> None:
    emit_codex(list_skills(), tmp_path)
    skill_md = tmp_path / ".codex" / "skills" / "optimization-targets" / "SKILL.md"
    assert skill_md.exists()
    # One level deep, name + description frontmatter — the codex contract.
    frontmatter = yaml.safe_load(skill_md.read_text().split("---")[1])
    assert frontmatter["name"] == "optimization-targets"


def test_emitters_are_idempotent(tmp_path: Path) -> None:
    emit_pi(list_skills(), tmp_path)
    second = emit_pi(list_skills(), tmp_path)
    assert second.written == []
    assert second.skipped_up_to_date


def test_sync_skills_cli_accepts_pi_and_codex(tmp_path: Path, capsys) -> None:
    from open_agent_compiler.cli.main import main

    rc = main(["sync-skills", str(tmp_path), "--skills", "pi,codex"])
    assert rc == 0
    assert (tmp_path / ".pi" / "skills").exists()
    assert (tmp_path / ".codex" / "skills").exists()
