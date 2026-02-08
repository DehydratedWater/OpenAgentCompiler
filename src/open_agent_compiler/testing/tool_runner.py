"""Subprocess wrapper for running tool scripts — exactly as agents do."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from open_agent_compiler.testing.scenario import ToolCommand


class ToolRunner:
    def __init__(self, project_root: Path, env: dict[str, str]) -> None:
        self.project_root = project_root
        self.env = env  # includes DATABASE_URL pointing to test DB

    def run(self, cmd: ToolCommand) -> dict[str, Any]:
        """Run a tool script, return parsed JSON output."""
        args = ["uv", "run", cmd.script]
        for k, v in cmd.args.items():
            args.extend([f"--{k}", str(v)])

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=self.project_root,
            env=self.env,
            timeout=60,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": (
                    f"Script exited with code "
                    f"{result.returncode}: "
                    f"{result.stderr.strip()}"
                ),
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        try:
            parsed: dict[str, Any] = json.loads(result.stdout)
            return parsed
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": f"Failed to parse JSON output: {result.stdout[:500]}",
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

    def run_sequence(self, commands: list[ToolCommand]) -> list[dict[str, Any]]:
        """Run multiple commands sequentially, return all outputs."""
        return [self.run(cmd) for cmd in commands]
