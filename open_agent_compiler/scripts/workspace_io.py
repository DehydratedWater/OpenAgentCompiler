#!/usr/bin/env python3
"""Sandboxed workspace file I/O for agents.

Read/write/list/delete inside a workspace directory only — all paths are
validated to refuse traversal outside. Session isolation via --run-id:
when provided, every operation is scoped to <workspace>/<run_id>/.

The workflow prompt's STEP 0a (Phase 3.2) emits a `--command init` call
which creates a fresh session and returns its run_id. The agent then
passes that run_id to every subsequent write/read/list/delete so
concurrent runs of the same agent don't interfere.

Usage:
    uv run scripts/workspace_io.py --command init --workspace <dir>
    uv run scripts/workspace_io.py --command write --workspace <dir> \\
        --run-id <id> --filename <name> < stdin
    uv run scripts/workspace_io.py --command read --workspace <dir> \\
        --run-id <id> --filename <name>
    uv run scripts/workspace_io.py --command list --workspace <dir> \\
        --run-id <id>
    uv run scripts/workspace_io.py --command delete --workspace <dir> \\
        --run-id <id> --filename <name>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path


def _resolve_workspace_root(workspace: str) -> Path:
    """Apply $XDG_DATA_HOME prefix to relative workspaces.

    Absolute paths are taken as-is. Relative paths get rooted under
    $XDG_DATA_HOME/oac (matching v1's convention) when the env is set;
    otherwise relative to CWD (matching v1's silent fallback).
    """
    p = Path(workspace)
    if p.is_absolute():
        return p
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "oac" / workspace
    return p


def _resolve_workspace(workspace: str, run_id: str | None = None) -> Path:
    ws = _resolve_workspace_root(workspace).resolve()
    if run_id:
        ws = ws / run_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _safe_path(workspace: Path, filename: str) -> Path:
    """Resolve filename within workspace, rejecting traversal attempts."""
    target = (workspace / filename).resolve()
    sep = os.sep
    if not str(target).startswith(str(workspace) + sep) and target != workspace:
        print(
            json.dumps({"success": False, "error": "Path traversal denied"}),
            file=sys.stderr,
        )
        sys.exit(1)
    return target


def cmd_init(workspace_root: str) -> dict:
    run_id = uuid.uuid4().hex[:12]
    ws = _resolve_workspace_root(workspace_root).resolve() / run_id
    ws.mkdir(parents=True, exist_ok=True)
    return {"success": True, "run_id": run_id, "path": str(ws)}


def cmd_write(workspace: Path, filename: str, content: str) -> dict:
    target = _safe_path(workspace, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return {"success": True, "path": str(target), "bytes": len(content)}


def cmd_read(workspace: Path, filename: str) -> dict:
    target = _safe_path(workspace, filename)
    if not target.exists():
        return {"success": False, "error": f"File not found: {filename}"}
    return {"success": True, "path": str(target), "content": target.read_text()}


def cmd_list(workspace: Path) -> dict:
    files = sorted(
        str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file()
    )
    return {"success": True, "files": files, "count": len(files)}


def cmd_delete(workspace: Path, filename: str) -> dict:
    target = _safe_path(workspace, filename)
    if not target.exists():
        return {"success": False, "error": f"File not found: {filename}"}
    target.unlink()
    return {"success": True, "path": str(target), "deleted": True}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Workspace file I/O")
    p.add_argument(
        "--command", required=True,
        choices=["init", "write", "read", "list", "delete"],
    )
    p.add_argument("--workspace", required=True, help="Workspace directory path")
    p.add_argument("--run-id", help="Session run ID for parallel isolation")
    p.add_argument("--filename", help="Target filename within workspace")
    return p


def main(argv: list[str] | None = None, *, stdin_content: str | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "init":
        print(json.dumps(cmd_init(args.workspace)))
        return 0

    workspace = _resolve_workspace(args.workspace, args.run_id)

    if args.command == "list":
        print(json.dumps(cmd_list(workspace)))
        return 0

    if args.filename is None:
        print(
            json.dumps({
                "success": False,
                "error": f"--filename required for {args.command}",
            }),
            file=sys.stderr,
        )
        return 1

    if args.command == "write":
        content = stdin_content if stdin_content is not None else sys.stdin.read()
        result = cmd_write(workspace, args.filename, content)
    elif args.command == "read":
        result = cmd_read(workspace, args.filename)
    elif args.command == "delete":
        result = cmd_delete(workspace, args.filename)
    else:  # pragma: no cover - argparse already restricts choices
        result = {"success": False, "error": f"Unknown command: {args.command}"}

    print(json.dumps(result))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
