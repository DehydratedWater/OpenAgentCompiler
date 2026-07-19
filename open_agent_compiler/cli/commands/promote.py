"""`oac promote` — re-introduce a snapshot back into the user's project."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from open_agent_compiler.improvement.snapshot import promote, read_snapshot


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "promote",
        help="Copy a snapshot JSON into .oac/promoted/ for the next compile.",
    )
    p.add_argument(
        "snapshot", type=Path,
        help="Path to a snapshot JSON file (typically under improved/<component>/<hash>.json).",
    )
    p.add_argument(
        "--project", type=Path, default=Path.cwd(),
        help="Project root (default: cwd).",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing promotion for the same component.",
    )
    p.add_argument(
        "--class", dest="model_class", default=None,
        help=(
            "Promote into the per-class slot under this label (writes"
            " .oac/promoted/<id>__<class>.json). Omit to promote to the"
            " default slot."
        ),
    )
    p.add_argument(
        "--target", default=None,
        help=(
            "Promote into a per-target slot (a run_per_target_loops key"
            " like 'pi+fast' or 'interactive'; writes"
            " .oac/promoted/<id>__<target>.json). Takes precedence over"
            " --class at load time: target > class > default."
        ),
    )
    p.add_argument(
        "--show", action="store_true",
        help="Print the snapshot's metrics + definition instead of promoting.",
    )


def handle(
    args: argparse.Namespace,
    load_factory: Callable[[str], Callable[[], Any]],
) -> int:
    if not args.snapshot.exists():
        raise FileNotFoundError(
            f"snapshot {args.snapshot} does not exist"
        )
    snap = read_snapshot(args.snapshot)
    if args.show:
        print(f"Component: {snap.version.component_id} ({snap.version.kind})")
        print(f"Hash: {snap.version.content_hash[:12]}…")
        print(f"Parent: {snap.version.parent_hash[:12] + '…' if snap.version.parent_hash else '(root)'}")
        print(f"Author: {snap.version.author}")
        print(f"Timestamp: {snap.version.timestamp}")
        print(f"Metrics: {snap.version.metrics}")
        print(f"Notes: {snap.notes}")
        return 0
    try:
        dest = promote(
            args.snapshot, args.project,
            force=args.force,
            model_class=args.model_class,
            target=args.target,
        )
    except FileExistsError as exc:
        print(f"oac promote: {exc}")
        return 2
    if args.target:
        class_suffix = f" [target={args.target}]"
    elif args.model_class:
        class_suffix = f" [class={args.model_class}]"
    else:
        class_suffix = ""
    print(
        f"oac promote: {snap.version.component_id}{class_suffix} → {dest}"
        " (pick up on next `python build_agents.py` run)"
    )
    return 0
