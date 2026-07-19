"""`oac sync-skills` — re-deploy or check developer skill bundles."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from open_agent_compiler.skills import (
    check_drift,
    emit_claude,
    emit_codex,
    emit_opencode,
    emit_pi,
    list_skills,
)

_VALID = {"opencode", "claude", "pi", "codex"}

_EMITTERS = {
    "opencode": emit_opencode,
    "claude": emit_claude,
    "pi": emit_pi,
    "codex": emit_codex,
}


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "sync-skills",
        help="Re-deploy developer skill bundles into a project.",
    )
    p.add_argument(
        "target", type=Path,
        help="Project directory whose .opencode/skills/ and .claude/skills/"
        " should be refreshed.",
    )
    p.add_argument(
        "--skills", default="opencode,claude",
        help=(
            "Comma-separated dialect list (subset of"
            " 'opencode,claude,pi,codex'; SKILL.md is the same cross-agent"
            " standard for all four). Default: 'opencode,claude'."
        ),
    )
    p.add_argument(
        "--force", action="store_true",
        help="Rewrite even when the installed sidecar matches the current hash.",
    )
    p.add_argument(
        "--check", action="store_true",
        help=(
            "Don't write anything; report which skills are fresh / stale /"
            " missing and exit 1 if any drift is detected."
        ),
    )


def _parse(value: str) -> tuple[str, ...]:
    skills = tuple(s.strip() for s in value.split(",") if s.strip())
    unknown = [s for s in skills if s not in _VALID]
    if unknown:
        raise ValueError(
            f"unknown skill dialects: {unknown}. Valid: {sorted(_VALID)}."
        )
    return skills


def handle(
    args: argparse.Namespace,
    load_factory: Callable[[str], Callable[[], Any]],
) -> int:
    skills = _parse(args.skills)
    if not args.target.exists() or not args.target.is_dir():
        raise FileNotFoundError(
            f"target {args.target} is not an existing directory"
        )
    bundles = list_skills()

    if args.check:
        any_drift = False
        for dialect in skills:
            reports = check_drift(bundles, args.target, dialect)
            for r in reports:
                status_label = {
                    "fresh": "OK   ",
                    "stale": "STALE",
                    "missing": "MISS ",
                }[r.status]
                print(
                    f"  [{status_label}] {dialect:8s} {r.skill_name}"
                    f" (current v{r.current_version})"
                )
                if r.status != "fresh":
                    any_drift = True
        return 1 if any_drift else 0

    total_written = 0
    for dialect in skills:
        out = _EMITTERS[dialect](bundles, args.target, force=args.force)
        print(
            f"oac sync-skills [{dialect}]: wrote {len(out.written)} file(s),"
            f" skipped {len(out.skipped_up_to_date)} up-to-date"
        )
        total_written += len(out.written)
    if total_written == 0:
        print("Everything was already up to date (pass --force to rewrite).")
    return 0
