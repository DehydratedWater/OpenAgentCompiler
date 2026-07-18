"""Static (AST) guard: no raw provider endpoints in a repo's loop code.

The non-negotiable Phase-0 constraint: the strong teacher (GLM / z.ai) is only
ever reached THROUGH opencode — never a raw provider HTTP call (ToS / ban risk).
Three consumers shipped raw `…/chat/completions` calls precisely because this
lived in hand-rolled consumer code. This shippable guard makes the rule
enforceable: a consumer imports `assert_no_raw_provider_endpoints(repo_root)` in
its own test suite, and the framework self-tests itself with it.

It scans Python source with `ast` and flags any STRING LITERAL that looks like a
raw provider endpoint (e.g. `api.z.ai`, `api.openai.com`, a bare
`/chat/completions` path) — EXCEPT module/class/function docstrings, which are
allowed to discuss the rule (this module does). Findings are reported as
`(file, lineno, snippet)`. Pure static analysis; runs nothing.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# Endpoint signatures that indicate a RAW provider call. Kept as substrings (not
# full URLs) so `f"{base}/chat/completions"` is caught even when the host is a
# variable. `api.z.ai` / `*.openai.com` catch hard-coded provider hosts.
RAW_PROVIDER_PATTERNS: tuple[str, ...] = (
    "api.z.ai",
    "open.bigmodel.cn",        # z.ai / zhipu raw host
    "/chat/completions",
    "/v1/chat/completions",
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",  # gemini raw
    "api.mistral.ai",
    "api.cohere.ai",
)

# Path globs excluded by default — vendored deps, virtualenvs, build artefacts.
DEFAULT_EXCLUDE: tuple[str, ...] = (
    "*/.venv/*", "*/venv/*", "*/site-packages/*", "*/node_modules/*",
    "*/.git/*", "*/build/*", "*/dist/*", "*/__pycache__/*",
)


@dataclass(frozen=True)
class Finding:
    """One flagged string literal."""

    file: str
    lineno: int
    snippet: str

    def __str__(self) -> str:
        return f"{self.file}:{self.lineno}: {self.snippet!r}"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """ids() of Constant nodes that are module/class/function docstrings.

    Docstrings legitimately discuss the rule (incl. the word `chat/completions`),
    so they are excluded from the scan.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def scan_source(source: str, *, filename: str = "<string>",
                patterns: tuple[str, ...] = RAW_PROVIDER_PATTERNS) -> list[Finding]:
    """Return findings for raw-provider-endpoint string literals in `source`.

    Skips docstrings. Raises nothing on a syntax error — an unparseable file
    yields no findings (the consumer's own lint catches syntax).
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []
    skip = _docstring_nodes(tree)
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        value = node.value
        for pat in patterns:
            if pat in value:
                findings.append(Finding(
                    file=filename, lineno=getattr(node, "lineno", 0),
                    snippet=value[:120],
                ))
                break
    return findings


def _excluded(path: Path, exclude: tuple[str, ...]) -> bool:
    s = str(path)
    return any(path.match(g) or re.search(g.replace("*", ".*"), s) for g in exclude)


def scan_repo(
    root: str | Path,
    *,
    patterns: tuple[str, ...] = RAW_PROVIDER_PATTERNS,
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE,
    include: tuple[str, ...] = ("*.py",),
) -> list[Finding]:
    """Scan every Python file under `root`, returning all findings.

    `include` selects files (default all `*.py`); `exclude` drops vendored/venv
    paths. Use `include=("*improve*.py", "*loop*.py", ...)` to scope to loop code.
    """
    root = Path(root)
    findings: list[Finding] = []
    files: list[Path] = []
    for pat in include:
        files.extend(root.rglob(pat))
    for f in sorted(set(files)):
        if _excluded(f, exclude):
            continue
        try:
            src = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(scan_source(src, filename=str(f), patterns=patterns))
    return findings


def assert_no_raw_provider_endpoints(
    root: str | Path,
    *,
    patterns: tuple[str, ...] = RAW_PROVIDER_PATTERNS,
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE,
    include: tuple[str, ...] = ("*.py",),
) -> None:
    """Assert NO raw provider endpoint appears in any Python file under `root`.

    Import this in a consumer's test suite:

        from open_agent_compiler.testing import assert_no_raw_provider_endpoints
        def test_no_raw_provider_calls():
            assert_no_raw_provider_endpoints(MY_REPO_ROOT)

    Raises AssertionError listing every offending `(file, line, snippet)`; the
    teacher must go through opencode (see OpencodeMutatorClient).
    """
    findings = scan_repo(root, patterns=patterns, exclude=exclude, include=include)
    if findings:
        listing = "\n".join(f"  - {f}" for f in findings)
        raise AssertionError(
            "Raw provider endpoint(s) found — route the teacher through opencode "
            f"(OpencodeMutatorClient), never a raw provider API:\n{listing}"
        )


__all__ = [
    "Finding",
    "RAW_PROVIDER_PATTERNS",
    "DEFAULT_EXCLUDE",
    "scan_source",
    "scan_repo",
    "assert_no_raw_provider_endpoints",
]
