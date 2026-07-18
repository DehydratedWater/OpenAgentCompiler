"""Compile/runtime helpers for the opencode autoloop (Phase 0 hardening).

These generalise the v4 field-report fixes that made candidate grading
reliable. They are deliberately file-level + dependency-light so any consumer
(whatever its registry/compile setup) can use them:

- `flat_candidate_from_project_root` — the #1 mass-zero fix. opencode discovers
  agents reliably only from a real PROJECT ROOT (the dir holding `opencode.json`)
  with a FLAT agent name (`cand_<hex>.md`). An ad-hoc temp dir with a
  nested/slashed name yields `Agent not found` ~50-70% of the time, which —
  silently swallowed as empty output — was the real cause of the mass-zeros.
- `warmup_discovery` — a freshly (re)started opencode server has a rescan lag:
  the FIRST dynamically added candidate isn't found yet. Run a throwaway flat
  candidate until it resolves so real grading never eats the lag.
- `tool_discipline_postamble` / `apply_tool_discipline` — the opt-in compile-time
  guard that stops a model debug-flailing on forbidden commands when a tool errors.
- `deps_env` — build the subprocess env that puts the deps-having interpreter
  first on PATH + propagates PYTHONPATH so an agent's `python scripts/*.py` tools
  import their deps (instead of dying on ModuleNotFoundError under system python).

None of these call opencode/qwen/z.ai; they only write files / build env dicts.
"""

from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path
from typing import Callable

# --- project-root discovery + flat candidate --------------------------------


def find_project_root(start: Path) -> Path:
    """Walk up from `start` to the nearest dir holding `opencode.json`.

    That dir is the opencode PROJECT ROOT — running candidates from it (and
    landing sessions in `<root>/.opencode/data`) is what makes agent discovery
    reliable and the sessions visible to a monitored opencode. Falls back to
    `start` if no `opencode.json` is found.
    """
    start = Path(start)
    for d in (start, *start.parents):
        if (d / "opencode.json").exists():
            return d
    return start


def flat_candidate_name(prefix: str = "cand") -> str:
    """A flat, collision-resistant candidate agent name, e.g. `cand_3f2a1b9c0d`."""
    return f"{prefix}_{secrets.token_hex(5)}"


def _repoint_model(text: str, model: str) -> str:
    """Rewrite the `model:` line of a compiled agent `.md` to `model`."""
    if re.search(r"^model:.*$", text, flags=re.M):
        return re.sub(r"^model:.*$", f"model: {model}", text, count=1, flags=re.M)
    # No frontmatter model line — inject one into the YAML block if present.
    if text.startswith("---"):
        return text.replace("---", f"---\nmodel: {model}", 1)
    return f"---\nmodel: {model}\n---\n{text}"


def flat_candidate_from_project_root(
    *,
    project_root: Path,
    compiled_md: Path | str | None = None,
    md_text: str | None = None,
    model: str | None = None,
    prefix: str = "cand",
    name: str | None = None,
) -> str:
    """Install a compiled agent FLAT-named into `<root>/.opencode/agents/`.

    Provide EITHER `compiled_md` (path to an already-compiled `<id>-primary.md`,
    typically produced in a temp dir) OR `md_text` (its raw markdown). Optionally
    `model` re-points the compiled `model:` line at the target provider (e.g. the
    local-qwen ref) so the candidate is tuned on the model that serves it.

    Returns the flat agent name to pass to `opencode run --agent <name>`.
    Idempotent on `name` if you pass one; otherwise a random `cand_<hex>`.
    """
    if (compiled_md is None) == (md_text is None):
        raise ValueError("pass exactly one of compiled_md or md_text")
    if md_text is None:
        md_text = Path(compiled_md).read_text(encoding="utf-8")
    if model is not None:
        md_text = _repoint_model(md_text, model)
    agents = Path(project_root) / ".opencode" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    flat = name or flat_candidate_name(prefix)
    (agents / f"{flat}.md").write_text(md_text, encoding="utf-8")
    return flat


def clear_candidates(project_root: Path, *, prefix: str = "cand") -> int:
    """Delete leftover `<prefix>_*.md` candidates from a previous run.

    Run ONCE before a fresh run so stale candidates don't accumulate. Teacher
    agents (named `teacher_*`) are intentionally not matched. Returns the count
    removed.
    """
    agents = Path(project_root) / ".opencode" / "agents"
    if not agents.exists():
        return 0
    n = 0
    for old in agents.glob(f"{prefix}_*.md"):
        old.unlink(missing_ok=True)
        n += 1
    return n


def warmup_discovery(
    *,
    project_root: Path,
    model: str,
    run: Callable[[str], object],
    attempts: int = 8,
    is_ok: Callable[[object], bool] | None = None,
) -> bool:
    """Prime opencode's agent discovery before grading starts.

    Writes a throwaway flat `cand_warmup` agent and invokes `run(agent_name)`
    until it resolves — so the first REAL candidate of a run isn't mis-scored 0
    by the server's first-scan lag. `run` is injected (the consumer's opencode
    invoker / an `OpencodeRunner.run` wrapper) so this stays test-friendly and
    never shells out itself. `is_ok` decides success (default: truthy result).
    Returns True if discovery resolved. Always cleans up the warmup agent.
    """
    if is_ok is None:
        is_ok = bool
    agents = Path(project_root) / ".opencode" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    md = agents / "cand_warmup.md"
    md.write_text(
        f"---\nmodel: {model}\n---\n"
        "You are a warmup probe. Reply with a single short sentence.\n"
    )
    try:
        for _ in range(max(1, attempts)):
            result = run("cand_warmup")
            if is_ok(result):
                return True
        return False
    finally:
        md.unlink(missing_ok=True)


# --- tool-discipline guard (opt-in compile flag) ----------------------------

TOOL_DISCIPLINE_POSTAMBLE = (
    "\n\nTOOL DISCIPLINE (strict): You may ONLY run the tools listed for you,"
    " with EXACTLY their documented form. NEVER run ls, find, cat, which, pip,"
    " python3, absolute paths, env inspection, or any install/debug command —"
    " they are blocked by your allow-list and waste the turn. If a tool returns"
    " an error, state the failure in ONE short line and continue with what you"
    " have; do NOT retry variations or try to inspect/fix the environment. Do"
    " NOT read source files, glob/list the codebase, or explore the filesystem"
    " to 'understand' your tools — their usage is documented above; just call"
    " them. Pointless reads/globs of files that may not exist waste the turn."
)


def tool_discipline_postamble() -> str:
    """The strict tool-discipline postamble (forbid ls/find/pip/which/python3/
    abs-paths + source-reading/globbing/exploration; report-once-and-continue).

    Opt-in: append it to an agent's postamble at compile time when the agent has
    a restrictive tool allow-list and you've seen debug-flailing. (~1800 denied
    calls/run fleet-wide before this guard; ~1 after.)
    """
    return TOOL_DISCIPLINE_POSTAMBLE


def apply_tool_discipline(definition: dict, *, postamble: str | None = None) -> dict:
    """Return a copy of an agent definition dict with the guard appended to
    `postamble`. Pure (no mutation of the input)."""
    guard = postamble if postamble is not None else TOOL_DISCIPLINE_POSTAMBLE
    out = dict(definition)
    out["postamble"] = (out.get("postamble") or "") + guard
    return out


# --- deps-env helper --------------------------------------------------------


def deps_env(
    *,
    interpreter: str | None = None,
    extra_path: list[Path | str] | None = None,
    pythonpath: list[Path | str] | None = None,
    propagate: tuple[str, ...] = (),
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess env an agent's `python scripts/*.py` tools need.

    An agent's bash runs bare `python scripts/X.py`, which otherwise hits the
    SYSTEM python (no deps, no PYTHONPATH) and dies on ModuleNotFoundError —
    producing nothing, scoring 0. This puts the deps-having `interpreter`'s
    directory FIRST on PATH (defaults to the current interpreter, i.e. the loop's
    own venv) and prepends `pythonpath` so `import`s resolve like production.

    `extra_path` adds more dirs after the interpreter (e.g. `~/.local/bin` for uv,
    `~/.opencode/bin` for opencode). `propagate` copies the named vars from the
    current environment if set. Returns env overrides to merge onto a run's env.
    """
    base = dict(base_env if base_env is not None else os.environ)
    venv_bin = str(Path(interpreter or sys.executable).parent)
    path_parts = [venv_bin]
    for p in extra_path or []:
        path_parts.append(str(p))
    existing_path = base.get("PATH", "")
    new_path = ":".join(path_parts) + (f":{existing_path}" if existing_path else "")

    out: dict[str, str] = {"PATH": new_path}

    pp_parts = [str(p) for p in (pythonpath or [])]
    existing_pp = base.get("PYTHONPATH", "")
    if existing_pp:
        pp_parts.append(existing_pp)
    if pp_parts:
        out["PYTHONPATH"] = ":".join(pp_parts)

    for key in propagate:
        if base.get(key):
            out[key] = base[key]
    return out


__all__ = [
    "find_project_root",
    "flat_candidate_name",
    "flat_candidate_from_project_root",
    "clear_candidates",
    "warmup_discovery",
    "TOOL_DISCIPLINE_POSTAMBLE",
    "tool_discipline_postamble",
    "apply_tool_discipline",
    "deps_env",
]
