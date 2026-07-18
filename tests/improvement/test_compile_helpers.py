"""Compile/runtime helpers — flat candidate, warmup, tool-discipline, deps-env.

Pins the v4 fixes that made candidate grading reliable. Pure file/env ops; no
live opencode/qwen.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.improvement.compile_helpers import (
    TOOL_DISCIPLINE_POSTAMBLE,
    apply_tool_discipline,
    clear_candidates,
    deps_env,
    find_project_root,
    flat_candidate_from_project_root,
    flat_candidate_name,
    warmup_discovery,
)


# --- find_project_root ------------------------------------------------------

def test_find_project_root_walks_up_to_opencode_json(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text("{}")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == tmp_path


def test_find_project_root_falls_back_to_start(tmp_path: Path) -> None:
    assert find_project_root(tmp_path) == tmp_path


# --- flat_candidate_from_project_root ---------------------------------------

def test_flat_candidate_from_text_writes_flat_md(tmp_path: Path) -> None:
    name = flat_candidate_from_project_root(
        project_root=tmp_path,
        md_text="---\nmodel: zai/x\n---\nbe helpful\n",
    )
    assert name.startswith("cand_")
    md = tmp_path / ".opencode" / "agents" / f"{name}.md"
    assert md.exists()
    assert "/" not in name  # FLAT — no nested/slashed name (the discovery killer)


def test_flat_candidate_repoints_model(tmp_path: Path) -> None:
    name = flat_candidate_from_project_root(
        project_root=tmp_path,
        md_text="---\nmodel: old/model\n---\nbody\n",
        model="local-qwen/q",
        name="cand_fixed",
    )
    assert name == "cand_fixed"
    txt = (tmp_path / ".opencode" / "agents" / "cand_fixed.md").read_text()
    assert "model: local-qwen/q" in txt
    assert "old/model" not in txt


def test_flat_candidate_from_compiled_md_path(tmp_path: Path) -> None:
    src = tmp_path / "tmp" / "a-primary.md"
    src.parent.mkdir(parents=True)
    src.write_text("---\nmodel: m\n---\nhi\n")
    root = tmp_path / "root"
    name = flat_candidate_from_project_root(project_root=root, compiled_md=src)
    assert (root / ".opencode" / "agents" / f"{name}.md").exists()


def test_flat_candidate_requires_exactly_one_source(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(ValueError):
        flat_candidate_from_project_root(project_root=tmp_path)


def test_flat_candidate_name_is_random_and_prefixed() -> None:
    a, b = flat_candidate_name(), flat_candidate_name()
    assert a != b and a.startswith("cand_")


# --- clear_candidates -------------------------------------------------------

def test_clear_candidates_removes_only_cand_files(tmp_path: Path) -> None:
    agents = tmp_path / ".opencode" / "agents"
    agents.mkdir(parents=True)
    (agents / "cand_a.md").write_text("x")
    (agents / "cand_b.md").write_text("x")
    (agents / "teacher_glm.md").write_text("x")  # must survive
    removed = clear_candidates(tmp_path)
    assert removed == 2
    assert (agents / "teacher_glm.md").exists()
    assert not (agents / "cand_a.md").exists()


# --- warmup_discovery -------------------------------------------------------

def test_warmup_retries_until_resolved_then_cleans_up(tmp_path: Path) -> None:
    calls = []

    def run(agent_name):
        calls.append(agent_name)
        return len(calls) >= 3  # resolves on the 3rd attempt

    ok = warmup_discovery(project_root=tmp_path, model="m", run=run)
    assert ok is True
    assert calls == ["cand_warmup", "cand_warmup", "cand_warmup"]
    # warmup agent cleaned up
    assert not (tmp_path / ".opencode" / "agents" / "cand_warmup.md").exists()


def test_warmup_returns_false_after_exhausting_attempts(tmp_path: Path) -> None:
    ok = warmup_discovery(
        project_root=tmp_path, model="m", run=lambda _n: False, attempts=2,
    )
    assert ok is False
    assert not (tmp_path / ".opencode" / "agents" / "cand_warmup.md").exists()


# --- tool-discipline guard --------------------------------------------------

def test_apply_tool_discipline_appends_guard() -> None:
    out = apply_tool_discipline({"name": "a", "postamble": "EXISTING"})
    assert out["postamble"].startswith("EXISTING")
    assert TOOL_DISCIPLINE_POSTAMBLE in out["postamble"]
    assert "NEVER run ls, find" in out["postamble"]


def test_apply_tool_discipline_is_pure() -> None:
    original = {"name": "a"}
    out = apply_tool_discipline(original)
    assert "postamble" not in original  # input untouched
    assert out["postamble"] == TOOL_DISCIPLINE_POSTAMBLE


def test_apply_tool_discipline_custom_postamble() -> None:
    out = apply_tool_discipline({"name": "a"}, postamble="\nCUSTOM")
    assert out["postamble"] == "\nCUSTOM"


# --- deps_env ---------------------------------------------------------------

def test_deps_env_puts_interpreter_first_on_path() -> None:
    env = deps_env(interpreter="/opt/venv/bin/python", base_env={"PATH": "/usr/bin"})
    assert env["PATH"].startswith("/opt/venv/bin:")
    assert env["PATH"].endswith(":/usr/bin")


def test_deps_env_prepends_pythonpath_and_propagates() -> None:
    env = deps_env(
        interpreter="/v/bin/python",
        pythonpath=["/proj", "/lib"],
        propagate=("DATABASE_URL", "MISSING"),
        base_env={"PATH": "/usr/bin", "PYTHONPATH": "/old",
                  "DATABASE_URL": "postgres://x"},
    )
    assert env["PYTHONPATH"] == "/proj:/lib:/old"
    assert env["DATABASE_URL"] == "postgres://x"
    assert "MISSING" not in env  # only propagated when set


def test_deps_env_adds_extra_path_dirs() -> None:
    env = deps_env(
        interpreter="/v/bin/python",
        extra_path=["/home/u/.local/bin", "/home/u/.opencode/bin"],
        base_env={"PATH": "/usr/bin"},
    )
    parts = env["PATH"].split(":")
    assert parts[:3] == ["/v/bin", "/home/u/.local/bin", "/home/u/.opencode/bin"]
