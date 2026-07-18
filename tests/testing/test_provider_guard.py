"""AST guard: no raw provider endpoints in loop code — + framework self-test."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.testing import (
    assert_no_raw_provider_endpoints,
    scan_repo,
    scan_source,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- scan_source ------------------------------------------------------------

def test_flags_chat_completions_string() -> None:
    src = 'url = base + "/chat/completions"\n'
    findings = scan_source(src, filename="x.py")
    assert len(findings) == 1
    assert findings[0].lineno == 1


def test_flags_hardcoded_provider_host() -> None:
    src = 'BASE = "https://api.z.ai/api/coding/paas/v4"\n'
    assert scan_source(src) and "api.z.ai" in scan_source(src)[0].snippet


def test_does_not_flag_docstring_discussing_the_rule() -> None:
    """A docstring may mention /chat/completions when explaining the ban."""
    src = (
        '"""Never call the raw /chat/completions endpoint; route via opencode."""\n'
        'x = 1\n'
    )
    assert scan_source(src) == []


def test_does_not_flag_clean_code() -> None:
    src = 'runner.run(agent_name="x", prompt="hi")\n'
    assert scan_source(src) == []


def test_syntax_error_yields_no_findings() -> None:
    assert scan_source("def (:\n") == []


def test_flags_multiple_providers() -> None:
    src = (
        'a = "api.openai.com/v1/chat/completions"\n'
        'b = "https://generativelanguage.googleapis.com/x"\n'
    )
    findings = scan_source(src)
    assert len(findings) == 2


# --- scan_repo + assertion --------------------------------------------------

def test_scan_repo_finds_planted_violation(tmp_path: Path) -> None:
    (tmp_path / "loop.py").write_text(
        'def go():\n    return post("https://api.z.ai/chat/completions")\n'
    )
    findings = scan_repo(tmp_path)
    assert any(f.file.endswith("loop.py") for f in findings)


def test_scan_repo_excludes_venv(tmp_path: Path) -> None:
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "vendored.py").write_text('x = "api.openai.com/chat/completions"\n')
    assert scan_repo(tmp_path) == []


def test_assert_raises_with_listing(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text('x = "/v1/chat/completions"\n')
    with pytest.raises(AssertionError) as exc:
        assert_no_raw_provider_endpoints(tmp_path)
    assert "bad.py" in str(exc.value)
    assert "opencode" in str(exc.value)


def test_assert_passes_on_clean_tree(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text('y = 1\n')
    assert_no_raw_provider_endpoints(tmp_path)  # no raise


# --- THE SELF-TEST: the framework's own improvement code is clean -----------

def test_framework_improvement_code_has_no_raw_provider_endpoints() -> None:
    """SHIP IT: the framework's loop/teacher code routes everything via opencode."""
    assert_no_raw_provider_endpoints(
        REPO_ROOT / "open_agent_compiler" / "improvement",
    )


def test_framework_testing_code_has_no_raw_provider_endpoints() -> None:
    # provider_guard.py itself only mentions the hosts in its pattern LIST, which
    # is the allow-pattern definition, not a call — but they live in a tuple of
    # string literals, so this module is intentionally excluded from the self-scan.
    findings = scan_repo(
        REPO_ROOT / "open_agent_compiler" / "testing",
        include=("*.py",),
    )
    offenders = [f for f in findings if not f.file.endswith("provider_guard.py")]
    assert offenders == [], offenders
