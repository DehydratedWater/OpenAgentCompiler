"""Repo recon — mine what the repeated work in this repository looks like.

Everything here is deterministic filesystem/git analysis (no LLM): the
profile it produces seeds the synthesized prompts and skills, and is
persisted as repo_profile.json in the harness so later evolution rounds
(and humans) can inspect what the harness believes about the repo.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

_LANG_EXTENSIONS = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".rs": "rust",
    ".go": "go", ".java": "java", ".rb": "ruby", ".php": "php",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cs": "csharp",
    ".swift": "swift", ".kt": "kotlin", ".sh": "shell",
}

_DOC_CANDIDATES = (
    "README.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "DEVELOPMENT.md",
    "docs", "doc",
)

_AGENT_INSTRUCTION_CANDIDATES = (
    "CLAUDE.md", "AGENTS.md", ".claude/skills", ".opencode/skills",
    ".claude/agents", ".opencode/agents", ".github/copilot-instructions.md",
)

_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build",
    "__pycache__", ".next", "target",
}

_CONVENTIONAL_RE = re.compile(r"^[a-z]+(\([^)]+\))?!?: ")


class CommitInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha: str
    subject: str
    files: tuple[str, ...] = ()


class RepoProfile(BaseModel):
    """What the harness knows about the repository it serves."""

    model_config = ConfigDict(frozen=True)

    name: str
    languages: dict[str, int] = Field(default_factory=dict)
    test_command: str | None = None
    build_command: str | None = None
    lint_command: str | None = None
    doc_files: tuple[str, ...] = ()
    agent_instructions: tuple[str, ...] = Field(
        default=(),
        description="Existing agent-facing files (CLAUDE.md, skills, …).",
    )
    conventional_commits: bool = False
    hot_paths: tuple[str, ...] = Field(
        default=(),
        description="Most frequently changed top-level areas (the repeated work).",
    )
    recent_commits: tuple[CommitInfo, ...] = ()

    @property
    def primary_language(self) -> str:
        if not self.languages:
            return "unknown"
        return max(self.languages, key=lambda k: self.languages[k])

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, text: str) -> "RepoProfile":
        return cls.model_validate_json(text)


def _git_log(repo: Path, max_commits: int) -> list[CommitInfo]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "log", f"-{max_commits}", "--no-merges",
         "--name-only", "--pretty=format:@@%H%n%s"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return []
    commits: list[CommitInfo] = []
    sha, subject, files = None, "", []
    for line in proc.stdout.splitlines():
        if line.startswith("@@"):
            if sha is not None:
                commits.append(CommitInfo(sha=sha, subject=subject,
                                          files=tuple(files)))
            sha, subject, files = line[2:], None, []  # type: ignore[assignment]
        elif subject is None:
            subject = line
        elif line.strip():
            files.append(line.strip())
    if sha is not None:
        commits.append(CommitInfo(sha=sha, subject=subject or "", files=tuple(files)))
    return commits


def _count_languages(repo: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in repo.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in _LANG_EXTENSIONS:
            counts[_LANG_EXTENSIONS[path.suffix]] += 1
    return dict(counts)


def _detect_commands(repo: Path) -> tuple[str | None, str | None, str | None]:
    """(test, build, lint) commands, best-effort from manifests."""
    test = build = lint = None
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        runner = "uv run " if (repo / "uv.lock").exists() else ""
        if "pytest" in content or (repo / "tests").exists():
            test = f"{runner}pytest"
        if "ruff" in content:
            lint = f"{runner}ruff check ."
        build = f"{runner}python -m build" if "[build-system]" in content else build
    package_json = repo / "package.json"
    if package_json.exists():
        try:
            scripts = json.loads(package_json.read_text()).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        if "test" in scripts:
            test = test or "npm test"
        if "build" in scripts:
            build = build or "npm run build"
        if "lint" in scripts:
            lint = lint or "npm run lint"
    if (repo / "Cargo.toml").exists():
        test = test or "cargo test"
        build = build or "cargo build"
        lint = lint or "cargo clippy"
    if (repo / "go.mod").exists():
        test = test or "go test ./..."
        build = build or "go build ./..."
    if (repo / "Makefile").exists():
        makefile = (repo / "Makefile").read_text()
        if test is None and re.search(r"^test:", makefile, re.M):
            test = "make test"
        if build is None and re.search(r"^build:", makefile, re.M):
            build = "make build"
        if lint is None and re.search(r"^lint:", makefile, re.M):
            lint = "make lint"
    return test, build, lint


def _hot_paths(commits: list[CommitInfo], top: int = 8) -> tuple[str, ...]:
    """Top-level areas by change frequency — where the repeated work is."""
    counts: Counter[str] = Counter()
    for commit in commits:
        seen_areas = set()
        for f in commit.files:
            area = f.split("/", 1)[0] if "/" in f else f
            seen_areas.add(area)
        counts.update(seen_areas)
    return tuple(area for area, _ in counts.most_common(top))


def _existing(repo: Path, candidates: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(c for c in candidates if (repo / c).exists())


def profile_repo(repo: Path, *, max_commits: int = 200) -> RepoProfile:
    commits = _git_log(repo, max_commits)
    test, build, lint = _detect_commands(repo)
    conventional = False
    if commits:
        matches = sum(1 for c in commits if _CONVENTIONAL_RE.match(c.subject))
        conventional = matches / len(commits) >= 0.5
    return RepoProfile(
        name=repo.name,
        languages=_count_languages(repo),
        test_command=test,
        build_command=build,
        lint_command=lint,
        doc_files=_existing(repo, _DOC_CANDIDATES),
        agent_instructions=_existing(repo, _AGENT_INSTRUCTION_CANDIDATES),
        conventional_commits=conventional,
        hot_paths=_hot_paths(commits),
        recent_commits=tuple(commits[:50]),
    )
