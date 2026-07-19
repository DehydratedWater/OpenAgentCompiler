"""Evolve coding harness: isolate, recon, synthesize, replay, teacher, zip."""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from open_agent_compiler.evolve import (
    ReferenceTask,
    RepoProfile,
    build_harness_registry,
    build_reference_evaluator,
    build_replay_evaluator,
    diff_similarity,
    file_overlap,
    generate_references,
    isolate_repo,
    output_similarity,
    package_harness,
    profile_repo,
    select_replay_commits,
    synthesize_harness,
)
from open_agent_compiler.evolve.isolate import assert_isolated
from open_agent_compiler.evolve.replay import replay_task_prompt, score_replay
from open_agent_compiler.improvement.version import ComponentVersion


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _make_source_repo(root: Path) -> Path:
    """A tiny python repo with history, docs, and a fake remote."""
    repo = root / "srcrepo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text(
        "[project]\nname='srcrepo'\n[tool.pytest.ini_options]\n[tool.ruff]\n"
    )
    (repo / "README.md").write_text("# srcrepo\n")
    (repo / "CLAUDE.md").write_text("Repo instructions.\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")

    (repo / "src" / "core.py").write_text("def add(a, b):\n    return a + b\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feat: initial core module")

    (repo / "src" / "core.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feat(core): add sub function")

    (repo / "tests" / "test_core.py").write_text(
        "from src.core import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "test: cover add")

    _git(repo, "remote", "add", "origin", "https://example.com/fake.git")
    return repo


@pytest.fixture()
def source_repo(tmp_path: Path) -> Path:
    return _make_source_repo(tmp_path)


@pytest.fixture()
def workspace_repo(tmp_path: Path, source_repo: Path) -> Path:
    return isolate_repo(source_repo, tmp_path / "ws")


# ---- isolate -----------------------------------------------------------


def test_isolate_strips_all_remotes(workspace_repo: Path) -> None:
    assert _git(workspace_repo, "remote").strip() == ""
    assert_isolated(workspace_repo)  # must not raise
    # History preserved for recon/replay.
    assert len(_git(workspace_repo, "log", "--oneline").splitlines()) == 3


def test_isolate_refuses_existing_dest(tmp_path: Path, source_repo: Path) -> None:
    isolate_repo(source_repo, tmp_path / "ws2")
    with pytest.raises(FileExistsError):
        isolate_repo(source_repo, tmp_path / "ws2")


def test_assert_isolated_rejects_connected_repo(source_repo: Path) -> None:
    with pytest.raises(RuntimeError, match="remotes"):
        assert_isolated(source_repo)


# ---- recon -------------------------------------------------------------


def test_profile_detects_repo_facts(workspace_repo: Path) -> None:
    profile = profile_repo(workspace_repo)
    assert profile.primary_language == "python"
    assert profile.test_command and "pytest" in profile.test_command
    assert profile.lint_command and "ruff" in profile.lint_command
    assert "README.md" in profile.doc_files
    assert "CLAUDE.md" in profile.agent_instructions
    assert profile.conventional_commits is True
    assert "src" in profile.hot_paths
    assert len(profile.recent_commits) == 3


def test_profile_roundtrips_through_json(workspace_repo: Path) -> None:
    profile = profile_repo(workspace_repo)
    again = RepoProfile.from_json(profile.to_json())
    assert again == profile


# ---- synthesize --------------------------------------------------------


def test_synthesize_compiles_harness_and_writes_scaffolding(
    workspace_repo: Path,
) -> None:
    profile = profile_repo(workspace_repo)
    written = synthesize_harness(workspace_repo, profile, skills=())
    agents_dir = workspace_repo / ".opencode" / "agents"
    assert (agents_dir / "implementer.md").exists()
    assert (agents_dir / "planner.md").exists()
    assert (agents_dir / "reviewer.md").exists()
    implementer = (agents_dir / "implementer.md").read_text()
    assert "pytest" in implementer          # repo facts baked into the prompt
    assert "review-pr" in implementer       # core skills present
    names = {p.name for p in written}
    assert names >= {"repo_profile.json", "agents.py", "build_harness.py",
                     "evolve_loop.py", "teacher_eval.py", "README.md"}
    # Generated python parses.
    import ast
    for p in written:
        if p.suffix == ".py":
            ast.parse(p.read_text())


def test_synthesize_deploys_developer_skills(workspace_repo: Path) -> None:
    profile = profile_repo(workspace_repo)
    synthesize_harness(workspace_repo, profile, skills=("opencode", "claude"))
    assert (workspace_repo / ".opencode" / "skills").exists()
    assert (workspace_repo / ".claude" / "skills").exists()
    skill_names = {
        p.name for p in (workspace_repo / ".opencode" / "skills").iterdir()
    }
    assert "autoloop-interview" in skill_names
    assert "optimization-targets" in skill_names


def test_harness_registry_loader_roundtrip(workspace_repo: Path) -> None:
    """The generated agents.py rebuilds the registry from repo_profile.json."""
    profile = profile_repo(workspace_repo)
    synthesize_harness(workspace_repo, profile, skills=())
    import sys
    harness_dir = str(workspace_repo / ".oac-harness")
    sys.path.insert(0, harness_dir)
    try:
        import agents as harness_agents
        reg = harness_agents.registry()
        assert any("implementer" in a for a in reg.list_agents())
        reg2 = harness_agents.registry(system_prompt="CANDIDATE")
        impl = reg2.get_agent(
            [a for a in reg2.list_agents() if "implementer" in a][0])
        assert impl.agent_definition.system_prompt == "CANDIDATE"
    finally:
        sys.path.remove(harness_dir)
        sys.modules.pop("agents", None)


# ---- replay ------------------------------------------------------------


def test_select_replay_commits_skips_rootless_and_big(workspace_repo: Path) -> None:
    commits = select_replay_commits(workspace_repo, n=10)
    # Root commit has no parent → excluded; the two later commits qualify.
    assert len(commits) == 2
    assert all(c.files for c in commits)


def test_similarity_math() -> None:
    assert file_overlap({"a", "b"}, {"a", "b"}) == 1.0
    assert file_overlap({"a"}, {"b"}) == 0.0
    assert file_overlap(set(), set()) == 1.0
    assert diff_similarity("same", "same") == 1.0
    assert diff_similarity("", "x") == 0.0
    assert 0.0 < diff_similarity("abc def", "abc xyz") < 1.0
    assert output_similarity("hello world", "hello world") == 1.0


def test_score_replay_perfect_reproduction(workspace_repo: Path) -> None:
    """A task runner that recreates the real change scores ~1."""
    commits = select_replay_commits(workspace_repo, n=1)
    commit = commits[0]  # "test: cover add"

    def perfect(prompt: str) -> None:
        (workspace_repo / "tests").mkdir(exist_ok=True)
        (workspace_repo / "tests" / "test_core.py").write_text(
            "from src.core import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
        )

    scores = score_replay(workspace_repo, commit, perfect)
    assert scores["file_overlap"] == 1.0
    assert scores["diff_similarity"] > 0.9
    # Workspace restored to the original checkout afterwards.
    assert (workspace_repo / "tests" / "test_core.py").exists()
    assert _git(workspace_repo, "status", "--porcelain").strip() == ""


def test_score_replay_restores_after_failure(workspace_repo: Path) -> None:
    commit = select_replay_commits(workspace_repo, n=1)[0]

    def boom(prompt: str) -> None:
        (workspace_repo / "junk.txt").write_text("x")
        raise RuntimeError("agent crashed")

    with pytest.raises(RuntimeError):
        score_replay(workspace_repo, commit, boom)
    assert not (workspace_repo / "junk.txt").exists()
    assert _git(workspace_repo, "status", "--porcelain").strip() == ""


class _ScriptedRunner:
    """Stub harness runner that applies a canned edit per prompt."""

    harness_name = "opencode"

    def __init__(self, workspace: Path, effect) -> None:
        self.workspace = workspace
        self.effect = effect

    def run(self, *, agent_name, prompt, timeout_s=None):
        self.effect(self.workspace, prompt)

        class _R:
            error = None
            succeeded = True

            def final_text(self_inner) -> str:
                return "done"

        return _R()


def test_build_replay_evaluator_end_to_end(workspace_repo: Path) -> None:
    profile = profile_repo(workspace_repo)
    synthesize_harness(workspace_repo, profile, skills=())
    commits = select_replay_commits(workspace_repo, n=1)

    def recreate(ws: Path, prompt: str) -> None:
        (ws / "tests").mkdir(exist_ok=True)
        (ws / "tests" / "test_core.py").write_text(
            "from src.core import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
        )

    evaluator = build_replay_evaluator(
        workspace_repo, commits,
        registry_factory=lambda defn: build_harness_registry(profile),
        runner=_ScriptedRunner(workspace_repo, recreate),
    )
    metrics = evaluator(ComponentVersion.of(
        component_id="implementer", kind="agent",
        definition={"system_prompt": "x"},
    ))
    assert metrics["pass_rate"] == 1.0
    assert metrics["score_mean"] > 0.9


def test_replay_task_prompt_hints_areas_not_files() -> None:
    from open_agent_compiler.evolve.replay import ReplayCommit
    prompt = replay_task_prompt(ReplayCommit(
        sha="x", subject="feat: add sub", files=("src/core.py",)))
    assert "feat: add sub" in prompt
    assert "src" in prompt
    assert "core.py" not in prompt  # locating the file is part of the job


# ---- teacher reference -------------------------------------------------


def test_reference_flow_and_gap_sink(workspace_repo: Path) -> None:
    profile = profile_repo(workspace_repo)
    synthesize_harness(workspace_repo, profile, skills=())
    tasks = [ReferenceTask(task_id="t1", prompt="do the thing")]

    teacher = _ScriptedRunner(
        workspace_repo, lambda ws, p: None)
    teacher.run = lambda **kw: type(  # teacher answers richly
        "R", (), {"error": None, "succeeded": True,
                  "final_text": lambda self: "step 1\nstep 2\nverified"},
    )()
    refs_path = workspace_repo / ".oac-harness" / "reference_outputs.json"
    refs = generate_references(
        workspace_repo, tasks,
        registry=build_harness_registry(profile),
        runner=teacher, out_path=refs_path,
    )
    assert refs["t1"].startswith("step 1")
    assert json.loads(refs_path.read_text())["t1"] == refs["t1"]

    student = _ScriptedRunner(workspace_repo, lambda ws, p: None)
    student.run = lambda **kw: type(
        "R", (), {"error": None, "succeeded": True,
                  "final_text": lambda self: "step 1\nsomething else"},
    )()
    gaps: dict = {}
    evaluator = build_reference_evaluator(
        workspace_repo, tasks, refs,
        registry_factory=lambda defn: build_harness_registry(profile),
        runner=student, gap_sink=gaps,
    )
    metrics = evaluator(ComponentVersion.of(
        component_id="implementer", kind="agent",
        definition={"system_prompt": "x"},
    ))
    assert 0.0 < metrics["score_mean"] < 1.0
    assert gaps["task_id"] == "t1"
    assert gaps["teacher_excerpt"].startswith("step 1")
    assert gaps["student_excerpt"].endswith("something else")


def test_teacher_gap_rewriter_uses_gap_evidence() -> None:
    from open_agent_compiler.improvement import TeacherGapRewriter
    from open_agent_compiler.improvement.mutators import MutationContext
    from open_agent_compiler.improvement.mutators.llm import _StubLLM

    llm = _StubLLM(response="ADAPTED PROMPT")
    gaps = {"task_id": "t1", "prompt": "do it", "score": 0.4,
            "teacher_excerpt": "teacher way", "student_excerpt": "student way"}
    mutator = TeacherGapRewriter(gap_source=lambda: gaps)
    parent = ComponentVersion.of(
        component_id="implementer", kind="agent",
        definition={"system_prompt": "old"},
    )
    child = mutator.mutate(parent, MutationContext(llm=llm))
    assert child is not None
    assert child.definition["system_prompt"] == "ADAPTED PROMPT"
    assert llm.calls[0]["context"]["teacher_excerpt"] == "teacher way"
    # Empty gap or closed gap → no-op.
    assert TeacherGapRewriter(gap_source=lambda: {}).mutate(
        parent, MutationContext(llm=llm)) is None
    assert TeacherGapRewriter(gap_source=lambda: {**gaps, "score": 0.99}).mutate(
        parent, MutationContext(llm=llm)) is None


# ---- package -----------------------------------------------------------


def test_package_harness_zips_repo_and_harness(
    tmp_path: Path, workspace_repo: Path,
) -> None:
    profile = profile_repo(workspace_repo)
    synthesize_harness(workspace_repo, profile, skills=())
    out = package_harness(workspace_repo, tmp_path / "harness.zip")
    names = zipfile.ZipFile(out).namelist()
    root = workspace_repo.name
    assert f"{root}/.oac-harness/repo_profile.json" in names
    assert f"{root}/.opencode/agents/implementer.md" in names
    assert any(n.startswith(f"{root}/.git/") for n in names)  # replay-capable
    without_git = package_harness(
        workspace_repo, tmp_path / "light.zip", include_git=False)
    assert not any(
        n.startswith(f"{root}/.git/")
        for n in zipfile.ZipFile(without_git).namelist()
    )


# ---- CLI ---------------------------------------------------------------


def test_cli_evolve_end_to_end(tmp_path: Path, source_repo: Path, capsys) -> None:
    from open_agent_compiler.cli.main import main

    out_dir = tmp_path / "evolved"
    rc = main([
        "evolve", str(source_repo), "--out", str(out_dir),
        "--skills", "", "--zip", str(tmp_path / "h.zip"),
    ])
    assert rc == 0
    output = capsys.readouterr().out
    assert "isolating" in output
    assert "commit(s) selected for replay" in output
    assert (out_dir / source_repo.name / ".oac-harness" / "evolve_loop.py").exists()
    assert (tmp_path / "h.zip").exists()
