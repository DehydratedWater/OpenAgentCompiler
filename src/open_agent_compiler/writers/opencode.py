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
        tool = compiled["tool"]
        config = {
            "provider": model["provider"],
            "model": model["id"],
            "theme": self._theme,
            "tool": tool,
        }
        path = self._output_dir / "opencode.json"
        path.write_text(json.dumps(config, indent=2) + "\n")

    def _write_agent_md(self, compiled: dict[str, Any]) -> None:
        agent = compiled["agent"]
        name: str = agent["name"]
        description: str = agent["description"]
        system_prompt: str = agent["system_prompt"]
        model: str = compiled["model"]["id"]
        tool: dict[str, Any] = compiled["tool"]

        agents_dir = self._output_dir / ".opencode" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        lines: list[str] = [
            "---",
            f"description: {description}",
            f"model: {model}",
        ]

        # Write tool: block
        lines.append("tool:")
        for key, value in tool.items():
            if isinstance(value, dict):
                lines.append(f"  {key}:")
                for pattern, rule in value.items():
                    lines.append(f'    "{pattern}": "{rule}"')
            elif isinstance(value, bool):
                lines.append(f"  {key}: {str(value).lower()}")
            else:
                lines.append(f"  {key}: {value}")

        # Write permission: block if present
        permission = compiled.get("permission")
        if permission is not None:
            lines.append("permission:")
            for key, value in permission.items():
                if isinstance(value, dict):
                    lines.append(f"  {key}:")
                    for pattern, rule in value.items():
                        lines.append(f'    "{pattern}": "{rule}"')
                else:
                    lines.append(f"  {key}: {value}")

        lines.append("---")
        lines.append("")
        lines.append(system_prompt)

        # Append skill instructions section if present
        skill_instructions: list[tuple[str, str]] = compiled.get(
            "skill_instructions", []
        )
        if skill_instructions:
            lines.append("")
            lines.append("## Available Skills")
            lines.append("")
            for skill_name, instruction in skill_instructions:
                lines.append(f"- **/{skill_name}**: {instruction}")

        lines.append("")

        path = agents_dir / f"{name}.md"
        path.write_text("\n".join(lines))

    def _write_skill_mds(self, compiled: dict[str, Any]) -> None:
        for skill in compiled["skills"]:
            skill_name: str = skill["name"]
            skill_dir = self._output_dir / ".opencode" / "skills" / skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)

            lines = [
                "---",
                f"name: {skill_name}",
                f"description: {skill['description']}",
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
