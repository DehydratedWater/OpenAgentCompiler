"""`oac evolve` — evolve a coding harness for an existing repository.

    oac evolve <repo> --out <workspace> [--dialect opencode] [--zip harness.zip]
    oac evolve <repo> --out <workspace> -i          # interactive setup

Pipeline: isolate (clone, strip remotes) → recon (RepoProfile) →
synthesize (repo-tailored agents + skills compiled into the workspace,
OAC developer skills deployed so a coding agent there can grow the
loop) → package (zip). The live evolution loop (commit replay) runs
from the generated `.oac-harness/evolve_loop.py` inside the workspace.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from open_agent_compiler.evolve import (
    isolate_repo,
    package_harness,
    profile_repo,
    select_replay_commits,
    synthesize_harness,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "evolve",
        help="Evolve a repo-tailored coding harness (isolated copy + agents"
             " + skills + replay-based autoloop).",
    )
    p.add_argument("repo", type=Path, help="Path to the repository to adapt to.")
    p.add_argument(
        "--out", type=Path, default=None,
        help="Workspace directory for the isolated copy"
             " (default: ./evolved_<repo-name>).",
    )
    p.add_argument(
        "-i", "--interactive", action="store_true",
        help="Prompt for every option instead of using flags/defaults.",
    )
    p.add_argument(
        "--dialect", default="opencode",
        help="Harness dialect the agents compile to (default: opencode).",
    )
    p.add_argument(
        "--model", default="zai-coding-plan/glm-4.5-air",
        help="Provider-qualified model for the synthesized agents.",
    )
    p.add_argument(
        "--reference-model", default="zai-coding-plan/glm-5.2",
        help="Stronger teacher model for teacher-gap evolution"
             " (.oac-harness/teacher_eval.py).",
    )
    p.add_argument(
        "--commits", type=int, default=5,
        help="Replay commits used for evolution scoring (default: 5).",
    )
    p.add_argument(
        "--skills", default="opencode,claude",
        help="Developer skill bundles to deploy in the workspace"
             " (subset of 'opencode,claude'; empty string = none).",
    )
    p.add_argument(
        "--native-tools", action="store_true",
        help="Compile the harness with native tool calling.",
    )
    p.add_argument(
        "--zip", dest="zip_path", type=Path, default=None,
        help="Also package the workspace as this zip file.",
    )
    p.add_argument(
        "--no-zip", action="store_true",
        help="Skip zip packaging (default zips to <out>.zip).",
    )


def _prompt(question: str, default: str) -> str:
    answer = input(f"{question} [{default}]: ").strip()
    return answer or default


def _interactive(args: argparse.Namespace) -> None:
    from open_agent_compiler.compiler.dialects import list_dialects

    print("oac evolve — interactive setup (enter accepts the default)")
    args.out = Path(_prompt(
        "  workspace directory",
        str(args.out or Path(f"evolved_{args.repo.name}")),
    ))
    dialects = "/".join(list_dialects())
    args.dialect = _prompt(f"  harness dialect ({dialects})", args.dialect)
    args.model = _prompt("  agent model (provider/model)", args.model)
    args.reference_model = _prompt(
        "  teacher model for gap evolution", args.reference_model)
    args.commits = int(_prompt("  replay commits for evolution", str(args.commits)))
    args.skills = _prompt("  deploy developer skills for", args.skills)
    zip_default = "" if args.no_zip else str(
        args.zip_path or Path(f"{args.out}.zip"))
    zip_answer = _prompt("  package zip path (empty = skip)", zip_default)
    if zip_answer:
        args.zip_path, args.no_zip = Path(zip_answer), False
    else:
        args.no_zip = True


def handle(
    args: argparse.Namespace,
    load_factory: Callable[[str], Callable[[], Any]],
) -> int:
    if args.interactive:
        _interactive(args)
    workspace = args.out or Path(f"evolved_{args.repo.name}")
    skills = tuple(s for s in args.skills.split(",") if s.strip())
    unknown = set(skills) - {"opencode", "claude"}
    if unknown:
        raise ValueError(
            f"unknown skill dialects: {sorted(unknown)}; valid: opencode, claude"
        )

    print(f"oac evolve: isolating {args.repo} → {workspace}/")
    repo_copy = isolate_repo(args.repo, workspace)
    print("oac evolve: profiling repository …")
    profile = profile_repo(repo_copy)
    print(
        f"  language={profile.primary_language}"
        f" test={profile.test_command or '-'}"
        f" conventional_commits={profile.conventional_commits}"
    )
    if profile.hot_paths:
        print(f"  hot paths: {', '.join(profile.hot_paths[:6])}")

    written = synthesize_harness(
        repo_copy, profile,
        dialect=args.dialect,
        model_name=args.model,
        reference_model=args.reference_model,
        replay_commits=args.commits,
        native_tools=args.native_tools,
        skills=skills,
    )
    print(f"oac evolve: synthesized harness ({len(written)} file(s) in"
          f" {repo_copy.name}/.oac-harness/, agents compiled for"
          f" {args.dialect})")

    replayable = select_replay_commits(repo_copy, n=args.commits)
    if replayable:
        print(f"oac evolve: {len(replayable)} commit(s) selected for replay"
              " evolution")
    else:
        print("oac evolve: no git history — replay evolution unavailable"
              " (harness still works)")

    if not args.no_zip:
        zip_path = args.zip_path or Path(f"{workspace}.zip")
        package_harness(repo_copy, zip_path)
        print(f"oac evolve: packaged → {zip_path}")

    print(
        "\nNext steps:\n"
        f"  cd {repo_copy}\n"
        f"  {args.dialect} run --agent implementer \"<a task>\"\n"
        "  uv run python .oac-harness/evolve_loop.py   # evolve via commit replay\n"
    )
    return 0
