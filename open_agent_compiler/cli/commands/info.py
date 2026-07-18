"""`oac info` — inspect a registry without compiling."""

from __future__ import annotations

import argparse
from typing import Any, Callable


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "info",
        help="List agents, templates, and configs registered on a factory.",
    )
    p.add_argument(
        "factory",
        nargs="?",
        help=(
            "module:callable returning an AgentRegistry. Optional when"
            " --dialects is given."
        ),
    )
    p.add_argument(
        "--dialects",
        action="store_true",
        help="List registered output dialects (for `oac compile --dialect`).",
    )


def handle(
    args: argparse.Namespace,
    load_factory: Callable[[str], Callable[[], Any]],
) -> int:
    if args.dialects:
        from open_agent_compiler.compiler.dialects.registry import list_dialects

        print(f"Dialects ({len(list_dialects())}):")
        for name in list_dialects():
            print(f"  {name}")
        if not args.factory:
            return 0
    if not args.factory:
        print("oac info: provide a factory (module:callable) or --dialects.")
        return 2
    factory = load_factory(args.factory)
    registry = factory()
    print(f"Agents ({len(registry.list_agents())}):")
    for agent_id in registry.list_agents():
        print(f"  {agent_id}")
    print(f"Templates ({len(registry.list_templates())}):")
    for name in registry.list_templates():
        print(f"  {name}")
    print(f"Configs ({len(registry.list_configs())}):")
    for name in registry.list_configs():
        print(f"  {name}")
    return 0
