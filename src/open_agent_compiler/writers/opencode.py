"""OpenCode writer — writes compiled agent dicts to disk as OpenCode project files."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


class OpenCodeWriter:
    """Writes compiled OpenCode agent configuration to the filesystem.

    Parameters
    ----------
    output_dir:
        Root directory for all build output.
    scripts_dir:
        Source directory containing handler scripts to copy.
        If ``None``, script copying is skipped.
    theme:
        OpenCode UI theme written into ``opencode.json``.
    """

    __slots__ = ("_output_dir", "_scripts_dir", "_theme")

    def __init__(
        self,
        output_dir: Path,
        scripts_dir: Path | None = None,
        *,
        theme: str = "dark",
    ) -> None:
        self._output_dir = output_dir
        self._scripts_dir = scripts_dir
        self._theme = theme

    def write(self, compiled: dict[str, Any]) -> None:
        """Write all OpenCode project files to *output_dir*."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._write_opencode_json(compiled)
        self._write_agent_md(compiled)
        self._write_skill_mds(compiled)
        if self._scripts_dir is not None:
            self._copy_scripts(compiled)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_opencode_json(self, compiled: dict[str, Any]) -> None:
        model = compiled["model"]
        tools = compiled["tools"]
        config = {
            "provider": model["provider"],
            "model": model["id"],
            "theme": self._theme,
            "tool": tools,
        }
        path = self._output_dir / "opencode.json"
        path.write_text(json.dumps(config, indent=2) + "\n")

    def _write_agent_md(self, compiled: dict[str, Any]) -> None:
        agent = compiled["agent"]
        name: str = agent["name"]
        description: str = agent["description"]
        system_prompt: str = agent["system_prompt"]

        agents_dir = self._output_dir / ".opencode" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        lines = [
            "---",
            f"name: {name}",
            f"description: {description}",
            "---",
            "",
            system_prompt,
            "",
        ]
        path = agents_dir / f"{name}.md"
        path.write_text("\n".join(lines))

    def _write_skill_mds(self, compiled: dict[str, Any]) -> None:
        for skill in compiled["skills"]:
            skill_name: str = skill["name"]
            skill_dir = self._output_dir / ".opencode" / "skills" / skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)

            tool_names: list[str] = skill["tools"]
            tools_yaml = ", ".join(tool_names) if tool_names else ""

            lines = [
                "---",
                f"name: {skill_name}",
                f"description: {skill['description']}",
                f"tools: [{tools_yaml}]",
                "---",
                "",
                skill["instructions"],
                "",
            ]
            path = skill_dir / "SKILL.md"
            path.write_text("\n".join(lines))

    def _copy_scripts(self, compiled: dict[str, Any]) -> None:
        assert self._scripts_dir is not None  # guarded by caller
        scripts_out = self._output_dir / "scripts"
        scripts_out.mkdir(parents=True, exist_ok=True)
        for script_file in compiled["scripts"]:
            src = self._scripts_dir / script_file
            dst = scripts_out / script_file
            if src.exists():
                shutil.copy2(src, dst)
