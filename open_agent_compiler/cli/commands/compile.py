"""`oac compile` — thin adapter over CompileScript."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from open_agent_compiler.compiler.script import CompileScript


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "compile",
        help="Compile a registered configuration to a target directory.",
    )
    p.add_argument(
        "factory",
        help="module:callable returning an AgentRegistry (e.g. 'myproj.agents:registry').",
    )
    p.add_argument(
        "--config",
        required=True,
        help="Name of a CompilationConfig registered on the returned AgentRegistry.",
    )
    p.add_argument(
        "--target",
        required=True,
        type=Path,
        help="Output directory for compiled artifacts.",
    )
    p.add_argument(
        "--dialect",
        default="opencode",
        help=(
            "Output dialect (default: opencode). Run `oac info --dialects`"
            " to list registered dialects."
        ),
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="Delete the target directory before writing.",
    )
    p.add_argument(
        "--native-tools",
        action="store_true",
        help=(
            "Also emit the harness's native tool-calling form for"
            " json-contract tools (.opencode/tool/*.ts shims for opencode;"
            " an MCP tools server for claude/codex)."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the configuration but do not write any files.",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print a one-line summary after the run.",
    )


def handle(
    args: argparse.Namespace,
    load_factory: Callable[[str], Callable[[], Any]],
) -> int:
    script = CompileScript(
        target=args.target,
        factory_spec=args.factory,
        config=args.config,
        dialect=args.dialect,
        clean=args.clean,
        native_tools=args.native_tools,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    result = script.run()
    if not args.verbose:
        label = "dry-run, would compile" if result.dry_run else "wrote"
        print(
            f"oac compile: {label} {len(result.resolved_slots)} slot(s) "
            f"-> {result.target}"
        )
    return 0
