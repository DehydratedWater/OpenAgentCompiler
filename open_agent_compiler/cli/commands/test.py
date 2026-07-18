"""`oac test` — run discovered tests + emit JSONL artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from open_agent_compiler.testing.orchestrate import TestRun


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "test", help="Discover + run embedded agent/tool tests.",
    )
    p.add_argument(
        "factory", help="module:callable returning an AgentRegistry.",
    )
    p.add_argument(
        "--config", required=True,
        help="CompilationConfig name to compile + test.",
    )
    p.add_argument(
        "--results", type=Path, default=Path(".oac/test_results.jsonl"),
        help="JSONL artifact path (default: .oac/test_results.jsonl).",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Bypass the green-hash cache; rerun every discovered test.",
    )
    p.add_argument(
        "--filter", dest="name_filter", default=None,
        help="Only run tests whose name contains this substring.",
    )
    p.add_argument(
        "--kind", dest="kind_filter",
        choices=["capability", "tool", "agent"], default=None,
        help="Only run tests of the given kind.",
    )
    p.add_argument(
        "--variant", dest="variant_name", default=None,
        help="Variant name to record in artifacts (informational).",
    )
    p.add_argument("-v", "--verbose", action="store_true")


def handle(
    args: argparse.Namespace,
    load_factory: Callable[[str], Callable[[], Any]],
) -> int:
    factory = load_factory(args.factory)
    run = TestRun(
        factory=factory,
        config=args.config,
        artifacts_path=args.results,
        force=args.force,
        name_filter=args.name_filter,
        kind_filter=args.kind_filter,
        variant_name=args.variant_name,
        verbose=args.verbose,
    )
    summary = run.run()
    print(
        f"\noac test: discovered={summary.discovered} "
        f"passed={summary.passed} failed={summary.failed} "
        f"skipped={summary.skipped} not_runnable={summary.not_runnable}"
    )
    if summary.failures:
        print("Failures:")
        for name, reason in summary.failures:
            print(f"  - {name}: {reason}")
    return 0 if summary.failed == 0 else 1
