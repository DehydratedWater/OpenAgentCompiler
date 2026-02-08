"""Bundled infrastructure scripts shipped as package data."""

from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent


def bundled_script_paths() -> list[Path]:
    """Return paths to all bundled .py scripts (excluding __init__)."""
    return [p for p in sorted(SCRIPTS_DIR.glob("*.py")) if p.name != "__init__.py"]
