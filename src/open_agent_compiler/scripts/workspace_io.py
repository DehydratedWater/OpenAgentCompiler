#!/usr/bin/env python3
"""Sandboxed workspace file I/O for agents.

Provides controlled read/write/list/delete within a workspace directory.
All paths are validated to prevent traversal outside the workspace.

Supports session isolation via ``--run-id``: when provided, all operations
are scoped to ``<workspace>/<run_id>/``.  Use ``--command init`` to generate
a fresh run ID and create the session directory.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path


def _resolve_workspace(workspace: str, run_id: str | None = None) -> Path:
    """Resolve and create workspace (or session) directory."""
    ws = Path(workspace).resolve()
    if run_id:
        ws = ws / run_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _safe_path(workspace: Path, filename: str) -> Path:
    """Resolve filename within workspace, rejecting traversal."""
    target = (workspace / filename).resolve()
    if not str(target).startswith(str(workspace) + "/") and target != workspace:
        print(
            json.dumps({"success": False, "error": "Path traversal denied"}),
            file=sys.stderr,
        )
        sys.exit(1)
    return target


def cmd_init(workspace_root: str) -> None:
    """Create a new session directory and return its run_id."""
    run_id = uuid.uuid4().hex[:12]
    ws = Path(workspace_root).resolve() / run_id
    ws.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"success": True, "run_id": run_id, "path": str(ws)}))


def cmd_write(workspace: Path, filename: str) -> None:
    """Write stdin content to workspace/filename."""
    target = _safe_path(workspace, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = sys.stdin.read()
    target.write_text(content)
    print(json.dumps({"success": True, "path": str(target), "bytes": len(content)}))


def cmd_read(workspace: Path, filename: str) -> None:
    """Read workspace/filename to stdout."""
    target = _safe_path(workspace, filename)
    if not target.exists():
        print(
            json.dumps({"success": False, "error": f"File not found: {filename}"}),
            file=sys.stderr,
        )
        sys.exit(1)
    content = target.read_text()
    print(json.dumps({"success": True, "path": str(target), "content": content}))


def cmd_list(workspace: Path) -> None:
    """List files in workspace."""
    files = sorted(
        str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file()
    )
    print(json.dumps({"success": True, "files": files, "count": len(files)}))


def cmd_delete(workspace: Path, filename: str) -> None:
    """Delete workspace/filename."""
    target = _safe_path(workspace, filename)
    if not target.exists():
        print(
            json.dumps({"success": False, "error": f"File not found: {filename}"}),
            file=sys.stderr,
        )
        sys.exit(1)
    target.unlink()
    print(json.dumps({"success": True, "path": str(target), "deleted": True}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Workspace file I/O")
    parser.add_argument(
        "--command",
        required=True,
        choices=["init", "write", "read", "list", "delete"],
    )
    parser.add_argument("--workspace", required=True, help="Workspace directory path")
    parser.add_argument("--run-id", help="Session run ID for parallel isolation")
    parser.add_argument("--filename", help="Target filename within workspace")
    args = parser.parse_args()

    # init is special — creates session dir, ignores --run-id
    if args.command == "init":
        cmd_init(args.workspace)
        return

    workspace = _resolve_workspace(args.workspace, args.run_id)

    if args.command == "list":
        cmd_list(workspace)
    elif args.filename is None:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"--filename required for {args.command}",
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    elif args.command == "write":
        cmd_write(workspace, args.filename)
    elif args.command == "read":
        cmd_read(workspace, args.filename)
    elif args.command == "delete":
        cmd_delete(workspace, args.filename)


if __name__ == "__main__":
    main()
