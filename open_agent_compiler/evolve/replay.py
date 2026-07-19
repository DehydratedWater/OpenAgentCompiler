"""Commit-replay evaluation — score the harness against the repo's own history.

The fitness function the user cares about is "does this harness produce
changes the way THIS repo's humans do?". The most grounded measure we
have is the repo's own history: take a real commit, hand the harness
its message as a task against the PARENT state, and score the diff the
harness produces against the diff that actually shipped —

    score = 0.5 * file_overlap (Jaccard on touched files)
          + 0.5 * diff_similarity (SequenceMatcher on unified diffs)

Deterministic and cheap; layer an `llm_judge` on the outputs when you
want qualitative judgment on top. `build_replay_evaluator` packages the
whole leg for `IterativeLoop`/`run_per_target_loops` with the standard
metric names, compiling each candidate registry into the workspace
first (same contract as compiled_eval's registry_factory).

Safety: replay only ever touches the ISOLATED workspace (isolate.py
guarantees no remotes; `assert_isolated` re-checks before every run).
The original checkout is restored after every probe, and untracked
harness files are preserved during cleanup.
"""

from __future__ import annotations

import difflib
import subprocess
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict

from open_agent_compiler.compiler.script import CompileScript
from open_agent_compiler.evolve.isolate import assert_isolated
from open_agent_compiler.evolve.recon import _git_log
from open_agent_compiler.improvement.harness_eval import HarnessRunner, get_runner
from open_agent_compiler.improvement.loop import Evaluator
from open_agent_compiler.improvement.version import ComponentVersion

# Cleanup must never delete the harness itself.
_HARNESS_EXCLUDES = (
    ".opencode", ".claude", ".pi", ".codex", ".oac-harness", ".oac",
    "scripts", "AGENTS.md", ".mcp.json", "improved",
)

_MAX_DIFF_CHARS = 20_000


class ReplayCommit(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha: str
    subject: str
    files: tuple[str, ...] = ()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False,
    )


def select_replay_commits(
    repo: Path, *, n: int = 5, max_files: int = 6, max_commits: int = 200,
) -> list[ReplayCommit]:
    """The most recent n non-merge commits touching 1..max_files files.

    Small-to-medium commits replay meaningfully; a 40-file refactor as a
    one-line task prompt would only measure noise.
    """
    out: list[ReplayCommit] = []
    for commit in _git_log(repo, max_commits):
        if not commit.files or len(commit.files) > max_files:
            continue
        # The very first commit has no parent to replay against.
        if _git(repo, "rev-parse", f"{commit.sha}^").returncode != 0:
            continue
        out.append(ReplayCommit(sha=commit.sha, subject=commit.subject,
                                files=commit.files))
        if len(out) >= n:
            break
    return out


def file_overlap(real: set[str], candidate: set[str]) -> float:
    """Jaccard similarity of touched-file sets."""
    if not real and not candidate:
        return 1.0
    if not real or not candidate:
        return 0.0
    return len(real & candidate) / len(real | candidate)


def diff_similarity(real_diff: str, candidate_diff: str) -> float:
    """SequenceMatcher ratio over (truncated) unified diffs."""
    if not real_diff.strip() and not candidate_diff.strip():
        return 1.0
    if not real_diff.strip() or not candidate_diff.strip():
        return 0.0
    return difflib.SequenceMatcher(
        None,
        real_diff[:_MAX_DIFF_CHARS],
        candidate_diff[:_MAX_DIFF_CHARS],
    ).ratio()


def replay_task_prompt(commit: ReplayCommit) -> str:
    """The task as the harness sees it — the commit message plus a hint
    at the area (not the exact files: locating them is part of the job)."""
    areas = sorted({f.split("/", 1)[0] for f in commit.files})
    hint = f" The change is somewhere under: {', '.join(areas)}." if areas else ""
    return (
        "Implement the following change in this repository, matching its"
        f" existing style:\n\n{commit.subject}\n{hint}\n"
        "Make the edits; do not commit."
    )


def score_replay(
    workspace: Path,
    commit: ReplayCommit,
    run_task: Callable[[str], None],
) -> dict[str, float]:
    """Replay ONE commit: checkout parent, run the task, diff, score, restore.

    `run_task(prompt)` drives the harness however the caller wants (a
    HarnessRunner in production, a stub in tests). Always restores the
    original checkout, preserving untracked harness files.
    """
    assert_isolated(workspace)
    original = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    branch = _git(workspace, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    real_diff = _git(workspace, "show", "--format=", commit.sha).stdout

    try:
        _git(workspace, "checkout", "--detach", f"{commit.sha}^")
        run_task(replay_task_prompt(commit))
        # Stage everything except the harness itself so NEW files count in
        # the diff (plain `git diff` only sees tracked changes).
        _git(workspace, "add", "-A", "--", ".",
             *[f":(exclude){name}" for name in _HARNESS_EXCLUDES])
        candidate_diff = _git(workspace, "diff", "--cached").stdout
        changed = set(
            _git(workspace, "diff", "--cached", "--name-only").stdout.split()
        )
    finally:
        _git(workspace, "reset", "--hard")
        _git(workspace, "clean", "-fd",
             *[arg for name in _HARNESS_EXCLUDES for arg in ("-e", name)])
        _git(workspace, "checkout", branch if branch != "HEAD" else original)

    overlap = file_overlap(set(commit.files), changed)
    similarity = diff_similarity(real_diff, candidate_diff)
    return {
        "file_overlap": overlap,
        "diff_similarity": similarity,
        "score": 0.5 * overlap + 0.5 * similarity,
    }


def build_replay_evaluator(
    workspace: Path,
    commits: list[ReplayCommit],
    *,
    registry_factory: Callable[[dict[str, Any]], Any],
    dialect: str = "opencode",
    config: str = "harness",
    agent_name: str = "implementer",
    runner: HarnessRunner | None = None,
    timeout_s: float | None = 600.0,
    native_tools: bool = False,
) -> Evaluator:
    """An IterativeLoop evaluator scoring candidates by commit replay.

    Per candidate: rebuild the registry (registry_factory receives the
    mutated definition dict), compile it into the workspace, then replay
    every commit through the harness runner and aggregate with the
    standard metric names (`pass_rate` / `score_floor` / `score_mean` /
    `score_floor:by_name:<sha>`), so criteria, gates, the store and
    promotion work unchanged.
    """

    def evaluator(version: ComponentVersion) -> dict[str, float]:
        registry = registry_factory(version.definition_copy())
        CompileScript(
            target=workspace, factory=lambda: registry, config=config,
            dialect=dialect, native_tools=native_tools,
        ).run()
        live_runner = runner or get_runner(dialect, workspace)

        scores: list[float] = []
        metrics: dict[str, float] = {}
        for commit in commits:
            def _run_task(prompt: str, _c=commit) -> None:
                result = live_runner.run(
                    agent_name=agent_name, prompt=prompt, timeout_s=timeout_s,
                )
                if result.error:
                    raise RuntimeError(f"harness run failed: {result.error}")

            try:
                outcome = score_replay(workspace, commit, _run_task)
                score = outcome["score"]
            except Exception:  # a failed replay scores 0, never crashes the loop
                score = 0.0
            scores.append(score)
            metrics[f"score_floor:by_name:{commit.sha[:10]}"] = score

        if scores:
            metrics["pass_rate"] = sum(1 for s in scores if s > 0) / len(scores)
            metrics["score_floor"] = min(scores)
            metrics["score_mean"] = sum(scores) / len(scores)
        return metrics

    return evaluator
