"""Tests for OpenCodeWriter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_agent_compiler.writers import OpenCodeWriter


class TestOpenCodeJson:
    def test_creates_valid_json(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        path = tmp_path / "opencode.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["provider"] == sample_compiled["model"]["provider"]
        assert data["model"] == sample_compiled["model"]["id"]
        assert data["tool"] == sample_compiled["tools"]

    def test_default_theme(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        data = json.loads((tmp_path / "opencode.json").read_text())
        assert data["theme"] == "dark"

    def test_custom_theme(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path, theme="catppuccin")
        writer.write(sample_compiled)

        data = json.loads((tmp_path / "opencode.json").read_text())
        assert data["theme"] == "catppuccin"


class TestAgentMd:
    def test_creates_agent_md(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        agent_name = sample_compiled["agent"]["name"]
        path = tmp_path / ".opencode" / "agents" / f"{agent_name}.md"
        assert path.exists()
        content = path.read_text()
        assert content.startswith("---\n")
        assert f"name: {agent_name}" in content
        assert sample_compiled["agent"]["description"] in content
        assert sample_compiled["agent"]["system_prompt"] in content


class TestSkillMds:
    def test_creates_skill_md(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        for skill in sample_compiled["skills"]:
            path = tmp_path / ".opencode" / "skills" / skill["name"] / "SKILL.md"
            assert path.exists()
            content = path.read_text()
            assert content.startswith("---\n")
            assert f"name: {skill['name']}" in content
            assert skill["description"] in content
            assert skill["instructions"] in content

    def test_skill_tools_in_frontmatter(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        for skill in sample_compiled["skills"]:
            path = tmp_path / ".opencode" / "skills" / skill["name"] / "SKILL.md"
            content = path.read_text()
            tool_names = ", ".join(skill["tools"])
            assert f"tools: [{tool_names}]" in content


class TestScriptCopying:
    def test_copies_scripts(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        scripts_src = tmp_path / "src_scripts"
        scripts_src.mkdir()
        for script in sample_compiled["scripts"]:
            (scripts_src / script).write_text(f"# {script}\n")

        out_dir = tmp_path / "build"
        writer = OpenCodeWriter(output_dir=out_dir, scripts_dir=scripts_src)
        writer.write(sample_compiled)

        for script in sample_compiled["scripts"]:
            assert (out_dir / "scripts" / script).exists()

    def test_skips_missing_scripts(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        scripts_src = tmp_path / "src_scripts"
        scripts_src.mkdir()
        # Don't create any script files — should not raise

        out_dir = tmp_path / "build"
        writer = OpenCodeWriter(output_dir=out_dir, scripts_dir=scripts_src)
        writer.write(sample_compiled)

        for script in sample_compiled["scripts"]:
            assert not (out_dir / "scripts" / script).exists()

    def test_no_scripts_dir_skips_copy(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        assert not (tmp_path / "scripts").exists()


class TestIdempotent:
    def test_write_twice_succeeds(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)
        writer.write(sample_compiled)

        assert (tmp_path / "opencode.json").exists()
