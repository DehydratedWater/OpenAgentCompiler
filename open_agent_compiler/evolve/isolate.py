"""Repo isolation — a full-history copy that CANNOT touch the upstream.

The evolved harness runs coding agents that edit, commit, and reset the
tree freely. Safety rule one: they must do that on a copy with no path
back to the real repository. `isolate_repo` clones (keeping history —
recon and replay need it) and then strips every remote; a plain
directory copy is the fallback for non-git sources (no history, so
replay evaluation is unavailable — recon degrades gracefully).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False,
    )


def is_git_repo(path: Path) -> bool:
    return _git(path, "rev-parse", "--git-dir").returncode == 0


def isolate_repo(source: Path, workspace: Path) -> Path:
    """Copy `source` into `workspace`/repo with no remotes. Returns the copy.

    Git sources are cloned with full history (`--no-hardlinks` so the
    copy shares nothing with the original object store), then every
    remote is removed and pushing is additionally disabled via
    `remote.pushDefault` removal — the isolated tree has no upstream to
    accidentally push to. Non-git sources are copied verbatim.
    """
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"repo source {source} does not exist")
    workspace.mkdir(parents=True, exist_ok=True)
    dest = workspace / source.name
    if dest.exists():
        raise FileExistsError(
            f"{dest} already exists — pick a fresh workspace or remove it"
        )

    if is_git_repo(source):
        clone = subprocess.run(
            ["git", "clone", "--no-hardlinks", str(source), str(dest)],
            capture_output=True, text=True, check=False,
        )
        if clone.returncode != 0:
            raise RuntimeError(f"git clone failed: {clone.stderr.strip()}")
        remotes = _git(dest, "remote").stdout.split()
        for remote in remotes:
            _git(dest, "remote", "remove", remote)
        # Belt and braces: even a manually re-added remote won't get a
        # default push destination.
        _git(dest, "config", "--unset", "remote.pushDefault")
        # A local identity so harness commits (replay resets, scratch
        # commits) never depend on the user's global git config.
        _git(dest, "config", "user.name", "oac-evolve")
        _git(dest, "config", "user.email", "oac-evolve@localhost")
    else:
        shutil.copytree(source, dest)

    return dest


def assert_isolated(repo: Path) -> None:
    """Raise if the workspace repo still has any remote configured."""
    if not is_git_repo(repo):
        return
    remotes = _git(repo, "remote").stdout.split()
    if remotes:
        raise RuntimeError(
            f"workspace repo {repo} still has remotes {remotes} —"
            " refusing to run the harness against a connected tree"
        )
