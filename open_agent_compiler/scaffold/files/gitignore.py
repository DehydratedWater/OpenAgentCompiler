"""`.gitignore` generator."""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render(config: ScaffoldConfig) -> str:
    lines = [
        "# Python",
        "__pycache__/",
        "*.py[oc]",
        "*.egg-info/",
        ".venv/",
        "dist/",
        "build/",
        "",
        "# Environment & secrets",
        ".env",
        ".env.local",
        "",
        "# OAC test + run artifacts",
        ".oac/",
        ".opencode/data/",
        ".agent_workspace/",
        "run_logs/",
    ]
    if config.with_cron:
        lines.append("cron/state/")
    return "\n".join(lines) + "\n"
