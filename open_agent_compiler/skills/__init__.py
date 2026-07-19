"""Developer skill bundles — teach a coding agent how to use this framework.

A SkillBundle is a piece of documentation aimed at OpenCode or Claude
Code (or any other coding agent that consumes markdown skills). The
content is opinionated and prescriptive: it doesn't just describe what
the framework does, it tells the agent how to do specific tasks
(adding new agents, writing tests, debugging Docker, ...).

Bundles are versioned and redeployable: `oac init --skills opencode`
writes them once; `oac sync-skills <target> --skills opencode` updates
them after a package upgrade.

This package layout:
- bundle.py — SkillBundle model + DialectTarget literal
- emitters.py — emit_opencode / emit_claude
- registry.py — list_skills / get_skill
- content/ — one module per topic, each exposing build() -> SkillBundle
"""

from open_agent_compiler.skills.bundle import DialectTarget, SkillBundle
from open_agent_compiler.skills.emitters import (
    DriftReport,
    DriftStatus,
    EmissionResult,
    check_drift,
    emit_claude,
    emit_codex,
    emit_opencode,
    emit_pi,
)
from open_agent_compiler.skills.registry import get_skill, list_skills

__all__ = [
    "DialectTarget",
    "SkillBundle",
    "DriftReport",
    "DriftStatus",
    "EmissionResult",
    "check_drift",
    "emit_claude",
    "emit_codex",
    "emit_opencode",
    "emit_pi",
    "get_skill",
    "list_skills",
]
