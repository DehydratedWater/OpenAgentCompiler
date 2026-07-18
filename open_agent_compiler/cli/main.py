"""`oac` — the open-agent-compiler command-line interface.

The CLI is a thin orchestrator over the same primitives a Python caller
would use directly: it loads a user-supplied factory that returns an
AgentRegistry, then dispatches to a subcommand (compile, info, test, …).

Subcommands keep their argparse setup in open_agent_compiler/cli/commands/<name>.py so
new commands stay decoupled from this entry module.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any, Callable

import open_agent_compiler
from open_agent_compiler.cli.commands import compile as compile_cmd
from open_agent_compiler.cli.commands import improve as improve_cmd
from open_agent_compiler.cli.commands import info as info_cmd
from open_agent_compiler.cli.commands import init as init_cmd
from open_agent_compiler.cli.commands import promote as promote_cmd
from open_agent_compiler.cli.commands import sync_skills as sync_skills_cmd
from open_agent_compiler.cli.commands import test as test_cmd

_COMMANDS: dict[str, Any] = {
    "compile": compile_cmd,
    "improve": improve_cmd,
    "info": info_cmd,
    "init": init_cmd,
    "promote": promote_cmd,
    "sync-skills": sync_skills_cmd,
    "test": test_cmd,
}


def _load_factory(spec: str) -> Callable[[], Any]:
    """Resolve a `module:callable` spec to the callable itself.

    The callable must take no arguments and return an AgentRegistry.

    The working directory is prepended to sys.path (mirroring `python -m`
    semantics) so `oac compile agents:registry` works from a scaffolded
    project root without installing the project first.
    """
    if ":" not in spec:
        raise ValueError(
            f"factory spec must be 'module:callable', got {spec!r}"
        )
    module_name, attr = spec.rsplit(":", 1)
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    module = importlib.import_module(module_name)
    factory = getattr(module, attr, None)
    if factory is None:
        raise ValueError(f"{module_name} has no attribute {attr!r}")
    if not callable(factory):
        raise ValueError(f"{spec} is not callable")
    return factory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oac",
        description="open-agent-compiler — compile composable agent trees.",
    )
    parser.add_argument(
        "--version", action="version", version=f"oac {open_agent_compiler.__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, mod in _COMMANDS.items():
        mod.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    handler = _COMMANDS[args.command].handle
    try:
        return handler(args, load_factory=_load_factory)
    except (ValueError, FileNotFoundError, ImportError, NotImplementedError) as exc:
        print(f"oac {args.command}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
