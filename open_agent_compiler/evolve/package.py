"""Package the evolved harness workspace into a handoff zip."""

from __future__ import annotations

import zipfile
from pathlib import Path

_SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".next", "target", "dist",
}


def package_harness(
    workspace_repo: Path,
    out_zip: Path,
    *,
    include_git: bool = True,
) -> Path:
    """Zip the workspace (repo + compiled harness + .oac-harness/).

    `include_git` keeps the isolated .git so replay evolution still
    works after unzipping (the clone has no remotes, so the zip stays
    push-safe); set False for a lighter artifact when only the harness
    matters.
    """
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    root = workspace_repo.resolve()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            parts = set(rel.parts)
            if parts & _SKIP_DIRS:
                continue
            if not include_git and rel.parts[0] == ".git":
                continue
            zf.write(path, arcname=str(Path(root.name) / rel))
    return out_zip
