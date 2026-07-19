"""apply_prompt_to_source — rewriting system_prompt literals in Python files."""

from __future__ import annotations

from pathlib import Path

import ast

import pytest

from open_agent_compiler.improvement.source_apply import (
    SourceApplyError,
    apply_prompt_to_source,
)

_AGENTS_PY = '''\
"""Example registry."""
from open_agent_compiler import AgentDefinition, AgentHeader

OTHER = AgentDefinition(
    header=AgentHeader(agent_id="other", name="other"),
    usage_explanation_long="l", usage_explanation_short="s",
    system_prompt="leave me alone",
)

GREETER = AgentDefinition(
    header=AgentHeader(agent_id="greeter", name="greeter",
                       description="A friendly greeter."),
    usage_explanation_long="l", usage_explanation_short="s",
    system_prompt="weak baseline prompt",  # tuned by autoloop
)
'''


def _write(tmp_path: Path, content: str = _AGENTS_PY) -> Path:
    path = tmp_path / "agents.py"
    path.write_text(content)
    return path


def test_rewrites_only_the_matching_definition(tmp_path: Path) -> None:
    path = _write(tmp_path)
    apply_prompt_to_source(path, "greeter", "IMPROVED prompt")
    out = path.read_text()
    assert "'IMPROVED prompt'" in out
    assert "weak baseline prompt" not in out
    assert '"leave me alone"' in out          # other agent untouched
    assert "# tuned by autoloop" in out       # surrounding bytes untouched
    ast.parse(out)                            # still valid Python


def test_multiline_prompt_becomes_triple_quoted(tmp_path: Path) -> None:
    path = _write(tmp_path)
    prompt = "Line one.\nLine two with \"quotes\".\nLine three."
    apply_prompt_to_source(path, "greeter", prompt)
    out = path.read_text()
    assert '"""' in out
    # The rewritten module evaluates back to exactly the new prompt.
    ns: dict = {}
    tree = ast.parse(out)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AgentDefinition":
            for kw in node.keywords:
                if kw.arg == "system_prompt" and isinstance(kw.value, ast.Constant):
                    ns[node.keywords[0].value.keywords[0].value.value] = kw.value.value
    assert ns["greeter"] == prompt


def test_unknown_component_raises(tmp_path: Path) -> None:
    path = _write(tmp_path)
    with pytest.raises(SourceApplyError, match="no AgentDefinition"):
        apply_prompt_to_source(path, "nope", "x")


def test_non_literal_prompt_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, _AGENTS_PY.replace(
        'system_prompt="weak baseline prompt",  # tuned by autoloop',
        "system_prompt=PROMPT_VAR,",
    ) + "\nPROMPT_VAR = 'x'\n")
    with pytest.raises(SourceApplyError, match="not a plain string literal"):
        apply_prompt_to_source(path, "greeter", "x")


def test_dry_run_leaves_file_untouched(tmp_path: Path) -> None:
    path = _write(tmp_path)
    rewritten = apply_prompt_to_source(path, "greeter", "NEW", write=False)
    assert "NEW" in rewritten
    assert "weak baseline prompt" in path.read_text()
