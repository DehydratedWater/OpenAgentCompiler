"""Scaffold state manifest — distinguishes framework-owned vs user-edited files.

Problem this solves: `oac init --force-overwrite` previously rewrote
every scaffold file unconditionally, including ones the user had
customised (agents/registry.py, pyproject.toml, .env.example). That
made it impossible to safely re-scaffold to pick up a framework fix
(e.g. when scaffold/files/db.py is updated, the user wants the new
db/repositories.py without losing their registry.py).

Solution: on every render, write `.oac/scaffold-state.json` with
the sha256 of each generated file's INITIAL content. On re-scaffold
with `--force-overwrite`:
  - If the file's CURRENT content matches the recorded hash, it's
    safe to overwrite (the user hasn't touched it).
  - If it differs, preserve the user's version + log a warning.

`--force-overwrite-all` keeps the old destructive behaviour for the
rare case where the user really does want to nuke everything.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_RELPATH = ".oac/scaffold-state.json"


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def manifest_path(target: Path) -> Path:
    return target / MANIFEST_RELPATH


def load_manifest(target: Path) -> dict[str, Any]:
    """Return the existing manifest dict, or an empty stub when absent.

    Manifest shape:
        {
          "schema_version": 1,
          "updated_at": ISO-8601 UTC,
          "files": {
            "<rel_path>": {"sha256": "<hex>", "first_seen": ISO-8601},
            ...
          }
        }
    """
    p = manifest_path(target)
    if not p.exists():
        return {"schema_version": 1, "files": {}}
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        # Treat a corrupted manifest as no-manifest — safer than
        # crashing mid-scaffold. The first overwrite will rewrite it.
        return {"schema_version": 1, "files": {}}
    return data


def write_manifest(
    target: Path, file_hashes: dict[str, str],
    *, previous: dict[str, Any] | None = None,
) -> Path:
    """Persist the manifest, preserving `first_seen` from any prior entry."""
    p = manifest_path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).isoformat()
    prev_files = (previous or {}).get("files", {})
    files: dict[str, dict[str, str]] = {}
    for rel, h in file_hashes.items():
        prior = prev_files.get(rel)
        first_seen = prior.get("first_seen") if isinstance(prior, dict) else now
        files[rel] = {"sha256": h, "first_seen": first_seen or now}
    out = {"schema_version": 1, "updated_at": now, "files": files}
    p.write_text(json.dumps(out, indent=2))
    return p


def classify_file(
    target: Path, rel_path: str, would_write: str,
    manifest: dict[str, Any],
) -> str:
    """Decide what to do with a file on re-scaffold.

    Returns one of:
      - 'fresh'       — file doesn't exist; safe to write.
      - 'unchanged'   — file exists; content matches what we'd write
                        (nothing to do).
      - 'framework'   — file exists; matches recorded hash (user
                        hasn't touched it); safe to overwrite.
      - 'user'        — file exists; differs from recorded hash;
                        preserve unless force_overwrite_all.
      - 'orphan'      — file exists; no manifest entry; treat as
                        user-owned to avoid clobbering pre-existing
                        files when the scaffold runs into an existing
                        directory.
    """
    full = target / rel_path
    if not full.exists():
        return "fresh"
    current = full.read_text() if full.is_file() else ""
    if current == would_write:
        return "unchanged"
    recorded = manifest.get("files", {}).get(rel_path)
    if not isinstance(recorded, dict):
        return "orphan"
    if recorded.get("sha256") == _hash(current):
        return "framework"
    return "user"


def compute_hash(content: str) -> str:
    """Public accessor for the sha256 we use to track scaffold state."""
    return _hash(content)
