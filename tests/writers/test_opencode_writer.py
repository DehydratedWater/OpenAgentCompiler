"""Tests for OpenCodeWriter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_agent_compiler._types import (
    AgentDefinition,
    AgentPermissions,
)
from open_agent_compiler.compiler import compile_agent
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
        assert data["$schema"] == "https://opencode.ai/config.json"
        assert data["model"] == sample_compiled["config"]["model"]

    def test_config_written_directly(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        data = json.loads((tmp_path / "opencode.json").read_text())
        assert data == sample_compiled["config"]

    def test_has_provider_hierarchy(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        data = json.loads((tmp_path / "opencode.json").read_text())
        assert "provider" in data
        assert "anthropic" in data["provider"]

    def test_has_compaction(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        data = json.loads((tmp_path / "opencode.json").read_text())
        assert data["compaction"] == {"auto": True, "prune": True}

    def test_no_agent_section_in_json(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        """opencode.json should not contain per-agent config."""
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        data = json.loads((tmp_path / "opencode.json").read_text())
        assert "agent" not in data


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
        assert sample_compiled["agent"]["description"] in content
        assert sample_compiled["agent"]["system_prompt"] in content

    def test_agent_md_has_tool_block(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        agent_name = sample_compiled["agent"]["name"]
        path = tmp_path / ".opencode" / "agents" / f"{agent_name}.md"
        content = path.read_text()
        assert "tool:" in content
        assert "bash:" in content
        assert "read: false" in content

    def test_agent_md_has_model(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        agent_name = sample_compiled["agent"]["name"]
        path = tmp_path / ".opencode" / "agents" / f"{agent_name}.md"
        content = path.read_text()
        assert f"model: {sample_compiled['config']['model']}" in content

    def test_agent_md_permission_block(self, tmp_path: Path) -> None:
        """Permission block renders in frontmatter when set."""
        agent = AgentDefinition(
            name="perm-agent",
            description="Agent with permissions",
            system_prompt="Hello",
            permissions=AgentPermissions(
                doom_loop="deny",
                task=((".opencode/agents/*.md", "allow"),),
            ),
        )
        compiled = compile_agent(agent)
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(compiled)

        path = tmp_path / ".opencode" / "agents" / "perm-agent.md"
        content = path.read_text()
        assert "permission:" in content
        assert '"*": deny' in content

    def test_agent_md_skill_instructions(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        """Skill instructions render in agent body."""
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        agent_name = sample_compiled["agent"]["name"]
        path = tmp_path / ".opencode" / "agents" / f"{agent_name}.md"
        content = path.read_text()
        assert "## Available Skills" in content
        assert "**/code-review**" in content
        assert "Use when reviewing code" in content

    def test_agent_md_skill_instructions_with_tools(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        """Skill instructions include tool sub-items."""
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        agent_name = sample_compiled["agent"]["name"]
        path = tmp_path / ".opencode" / "agents" / f"{agent_name}.md"
        content = path.read_text()
        # The sample_skill has a read_file tool
        assert "**read_file**" in content
        assert "Read a file from disk" in content

    def test_agent_md_deny_first_in_bash(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        """Deny rule appears before allow rules in bash block."""
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        agent_name = sample_compiled["agent"]["name"]
        path = tmp_path / ".opencode" / "agents" / f"{agent_name}.md"
        content = path.read_text()
        # Find positions of deny and allow in bash block
        deny_pos = content.find('"*": "deny"')
        allow_pos = content.find('"uv run scripts/')
        assert deny_pos < allow_pos

    def test_agent_md_no_model_when_empty(self, tmp_path: Path) -> None:
        """No model line when default_model is empty."""
        agent = AgentDefinition(name="no-model", description="Test", system_prompt="Hi")
        compiled = compile_agent(agent)
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(compiled)

        path = tmp_path / ".opencode" / "agents" / "no-model.md"
        content = path.read_text()
        assert "model:" not in content

    def test_agent_md_per_agent_fields(self, tmp_path: Path) -> None:
        """Per-agent config fields render in .md frontmatter."""
        agent = AgentDefinition(
            name="rich-agent",
            description="Agent with all fields",
            system_prompt="Hi",
            mode="primary",
            variant="fast",
            temperature=0.5,
            top_p=0.9,
            hidden=True,
            color="#FF5733",
            steps=50,
            options=(("reasoning_effort", "high"),),
        )
        compiled = compile_agent(agent)
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(compiled)

        path = tmp_path / ".opencode" / "agents" / "rich-agent.md"
        content = path.read_text()
        assert "variant: fast" in content
        assert "temperature: 0.5" in content
        assert "top_p: 0.9" in content
        assert "mode: primary" in content
        assert "hidden: true" in content
        assert 'color: "#FF5733"' in content
        assert "steps: 50" in content
        assert "options:" in content
        assert 'reasoning_effort: "high"' in content

    def test_agent_md_omits_defaults(self, tmp_path: Path) -> None:
        """Default per-agent values are not emitted."""
        agent = AgentDefinition(
            name="minimal", description="Minimal", system_prompt="Hi"
        )
        compiled = compile_agent(agent)
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(compiled)

        path = tmp_path / ".opencode" / "agents" / "minimal.md"
        content = path.read_text()
        assert "variant:" not in content
        assert "temperature:" not in content
        assert "top_p:" not in content
        assert "hidden:" not in content
        assert "color:" not in content
        assert "steps:" not in content
        assert "options:" not in content


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

    def test_skill_no_tools_in_frontmatter(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        """Skills should not have a tools: line in frontmatter."""
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        for skill in sample_compiled["skills"]:
            path = tmp_path / ".opencode" / "skills" / skill["name"] / "SKILL.md"
            content = path.read_text()
            assert "tools:" not in content


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

        out_dir = tmp_path / "build"
        writer = OpenCodeWriter(output_dir=out_dir, scripts_dir=scripts_src)
        writer.write(sample_compiled)

        for script in sample_compiled["scripts"]:
            assert not (out_dir / "scripts" / script).exists()

    def test_no_scripts_dir_skips_user_script_copy(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)

        # Bundled scripts are always copied, but user scripts are not
        scripts_dir = tmp_path / "scripts"
        assert scripts_dir.exists()  # bundled scripts directory exists
        for script in sample_compiled["scripts"]:
            assert not (scripts_dir / script).exists()  # user scripts not copied


class TestIdempotent:
    def test_write_twice_succeeds(
        self, tmp_path: Path, sample_compiled: dict[str, Any]
    ) -> None:
        writer = OpenCodeWriter(output_dir=tmp_path)
        writer.write(sample_compiled)
        writer.write(sample_compiled)

        assert (tmp_path / "opencode.json").exists()
