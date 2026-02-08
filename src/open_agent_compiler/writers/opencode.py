"""OpenCode writer — writes compiled agent dicts to disk as OpenCode project files."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from open_agent_compiler.scripts import bundled_script_paths


class OpenCodeWriter:
    """Writes compiled OpenCode agent configuration to the filesystem.

    Parameters
    ----------
    output_dir:
        Root directory for all build output.
    scripts_dir:
        Source directory containing handler scripts to copy.
        If ``None``, script copying is skipped.
    """

    __slots__ = ("_output_dir", "_scripts_dir")

    def __init__(
        self,
        output_dir: Path,
        scripts_dir: Path | None = None,
    ) -> None:
        self._output_dir = output_dir
        self._scripts_dir = scripts_dir

    def write(self, compiled: dict[str, Any]) -> None:
        """Write all OpenCode project files to *output_dir*."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._write_opencode_json(compiled)
        self._write_agent_md(compiled)
        self._write_subagent_mds(compiled)
        self._write_skill_mds(compiled)
        self._copy_bundled_scripts()
        if self._scripts_dir is not None:
            self._copy_scripts(compiled)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _copy_bundled_scripts(self) -> None:
        """Copy bundled infrastructure scripts to output scripts/ dir.

        Only copies files that don't already exist, so locally formatted
        copies are not overwritten on subsequent builds.
        """
        scripts_out = self._output_dir / "scripts"
        scripts_out.mkdir(parents=True, exist_ok=True)
        for src in bundled_script_paths():
            dst = scripts_out / src.name
            if not dst.exists():
                shutil.copy2(src, dst)

    def _write_opencode_json(self, compiled: dict[str, Any]) -> None:
        config = compiled["config"]
        path = self._output_dir / "opencode.json"
        path.write_text(json.dumps(config, indent=2) + "\n")

    def _write_agent_md(self, compiled: dict[str, Any]) -> None:
        agent = compiled["agent"]
        name: str = agent["name"]
        description: str = agent["description"]
        system_prompt: str = agent["system_prompt"]
        config: dict[str, Any] = compiled["config"]
        model: str = config.get("model", "")
        tool: dict[str, Any] = compiled["tool"]

        agents_dir = self._output_dir / ".opencode" / "agents"
        if agent.get("agent_dir"):
            agents_dir = agents_dir / agent["agent_dir"]
        agents_dir.mkdir(parents=True, exist_ok=True)

        lines: list[str] = [
            "---",
            f"description: {description}",
        ]

        if model:
            lines.append(f"model: {model}")

        # Per-agent config fields
        if "variant" in agent:
            lines.append(f"variant: {agent['variant']}")
        if "temperature" in agent:
            lines.append(f"temperature: {agent['temperature']}")
        if "top_p" in agent:
            lines.append(f"top_p: {agent['top_p']}")
        if "min_p" in agent:
            lines.append(f"min_p: {agent['min_p']}")
        if "top_k" in agent:
            lines.append(f"top_k: {agent['top_k']}")
        if "presence_penalty" in agent:
            lines.append(f"presence_penalty: {agent['presence_penalty']}")
        if "mode" in agent:
            lines.append(f"mode: {agent['mode']}")
        if agent.get("hidden"):
            lines.append("hidden: true")
        if "color" in agent:
            lines.append(f'color: "{agent["color"]}"')
        if "steps" in agent:
            lines.append(f"steps: {agent['steps']}")
        if "trigger_command" in agent:
            lines.append(f'trigger_command: "{agent["trigger_command"]}"')
        if "input_placeholder" in agent:
            lines.append(f'input_placeholder: "{agent["input_placeholder"]}"')
        if "options" in agent:
            lines.append("options:")
            for opt_key, opt_val in agent["options"].items():
                if isinstance(opt_val, bool):
                    lines.append(f"  {opt_key}: {str(opt_val).lower()}")
                elif isinstance(opt_val, str):
                    lines.append(f'  {opt_key}: "{opt_val}"')
                else:
                    lines.append(f"  {opt_key}: {opt_val}")

        # Write tool: block
        lines.append("tool:")
        for key, value in tool.items():
            # Quote pattern keys (contain glob chars like *)
            qk = f'"{key}"' if "*" in key or "?" in key else key
            if isinstance(value, dict):
                lines.append(f"  {qk}:")
                for pattern, rule in value.items():
                    if isinstance(rule, bool):
                        lines.append(f'    "{pattern}": {str(rule).lower()}')
                    else:
                        lines.append(f'    "{pattern}": "{rule}"')
            elif isinstance(value, bool):
                lines.append(f"  {qk}: {str(value).lower()}")
            else:
                lines.append(f"  {qk}: {value}")

        # Write permission: block if present
        permission = compiled.get("permission")
        if permission is not None:
            lines.append("permission:")
            for key, value in permission.items():
                qk = f'"{key}"' if "*" in key or "?" in key else key
                if isinstance(value, dict):
                    lines.append(f"  {qk}:")
                    for pattern, rule in value.items():
                        lines.append(f'    "{pattern}": "{rule}"')
                else:
                    lines.append(f"  {qk}: {value}")

        lines.append("---")
        lines.append("")
        lines.append(system_prompt)

        # Append skill instructions section if present
        skill_instructions: list[dict[str, Any]] = compiled.get(
            "skill_instructions", []
        )
        if skill_instructions:
            lines.append("")
            lines.append("## Available Skills")
            lines.append("")
            for entry in skill_instructions:
                lines.append(f"- **/{entry['name']}**: {entry['instruction']}")
                for tool_info in entry.get("tools", []):
                    lines.append(
                        f"  - **{tool_info['name']}**: {tool_info['description']}"
                    )

        lines.append("")

        path = agents_dir / f"{name}.md"
        path.write_text("\n".join(lines))

    def _write_subagent_mds(self, compiled: dict[str, Any]) -> None:
        for sa in compiled.get("subagents_compiled", []):
            agents_dir = self._output_dir / ".opencode" / "agents"
            if sa.get("agent_dir"):
                agents_dir = agents_dir / sa["agent_dir"]
            agents_dir.mkdir(parents=True, exist_ok=True)

            lines: list[str] = [
                "---",
                f"description: {sa['description']}",
                "mode: subagent",
                "---",
                "",
            ]
            if sa.get("notes"):
                lines.append(sa["notes"])
                lines.append("")

            path = agents_dir / f"{sa['name']}.md"
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
