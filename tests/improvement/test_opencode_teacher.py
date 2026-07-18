"""OpencodeMutatorClient — the teacher routed through opencode (no raw API).

Pins the ban-risk fix: the strong teacher (rewriter + judge) runs as a flat
opencode agent, never a raw provider HTTP call. All runs go through a FAKE
runner — no live opencode/z.ai.
"""

from __future__ import annotations

import json
from pathlib import Path

from open_agent_compiler.improvement import LLMPromptRewriter, MutationContext, OpencodeMutatorClient
from open_agent_compiler.improvement.mutators.opencode_teacher import (
    install_teacher_agent,
    normalize_model_ref,
    teacher_agent_name,
)
from open_agent_compiler.improvement.opencode_eval import OpencodeRunResult
from open_agent_compiler.improvement.version import ComponentVersion


class _FakeRunner:
    """Stand-in for OpencodeRunner: records runs, returns canned stdout text."""

    def __init__(self, text: str = "REWRITTEN PROMPT", *, error: bool = False) -> None:
        self.text = text
        self.error = error
        self.calls: list[dict] = []

    def run(self, *, agent_name, prompt, timeout_s=None, extra_env=None, extra_args=None):
        self.calls.append({"agent_name": agent_name, "prompt": prompt})
        stdout = "" if self.error else json.dumps(
            {"type": "text", "part": {"text": self.text}}
        )
        if self.error:
            stdout = json.dumps(
                {"type": "error", "error": {"data": {"message": "Agent not found"}}}
            )
        return OpencodeRunResult(
            agent_name=agent_name, prompt=prompt, stdout=stdout,
            stderr="", return_code=0, elapsed_s=0.0,
        )


def test_normalize_model_ref_adds_provider() -> None:
    assert normalize_model_ref("glm-5.1") == "zai-coding-plan/glm-5.1"
    assert normalize_model_ref("anthropic/claude") == "anthropic/claude"


def test_install_writes_flat_teacher_agent(tmp_path: Path) -> None:
    name = install_teacher_agent(tmp_path, "zai-coding-plan/glm-5.1")
    assert name == teacher_agent_name("zai-coding-plan/glm-5.1")
    md = tmp_path / ".opencode" / "agents" / f"{name}.md"
    assert md.exists()
    assert "model: zai-coding-plan/glm-5.1" in md.read_text()
    # named so a `cand_*` cleanup never deletes it
    assert not name.startswith("cand_")


def test_rewrite_returns_teacher_text(tmp_path: Path) -> None:
    runner = _FakeRunner("A much better prompt.")
    client = OpencodeMutatorClient(workspace=tmp_path, runner=runner)
    out = client.rewrite("old prompt", "fix it", context={"failures": [{"x": 1}]})
    assert out == "A much better prompt."
    # routed through opencode: the run used the flat teacher agent + folded prompt
    assert len(runner.calls) == 1
    assert runner.calls[0]["agent_name"] == client.agent_name
    assert "CURRENT SYSTEM PROMPT" in runner.calls[0]["prompt"]


def test_rewrite_strips_code_fences(tmp_path: Path) -> None:
    runner = _FakeRunner("```\nclean prompt\n```")
    client = OpencodeMutatorClient(workspace=tmp_path, runner=runner)
    assert client.rewrite("old", "fix") == "clean prompt"


def test_rewrite_falls_back_to_target_on_error(tmp_path: Path) -> None:
    """A surfaced opencode error → keep the original prompt (no garbage)."""
    runner = _FakeRunner(error=True)
    client = OpencodeMutatorClient(workspace=tmp_path, runner=runner)
    assert client.rewrite("ORIGINAL", "fix") == "ORIGINAL"


def test_judge_parses_score_json(tmp_path: Path) -> None:
    runner = _FakeRunner('{"score": 0.9, "reasoning": "great"}')
    client = OpencodeMutatorClient(workspace=tmp_path, runner=runner)
    verdict = client.judge("does it answer?", "a good answer")
    assert verdict == {"pass": True, "score": 0.9, "reasoning": "great"}


def test_judge_clamps_and_fails_below_threshold(tmp_path: Path) -> None:
    runner = _FakeRunner('{"score": 0.3}')
    client = OpencodeMutatorClient(workspace=tmp_path, runner=runner, pass_threshold=0.7)
    verdict = client.judge("crit", "weak")
    assert verdict["pass"] is False
    assert verdict["score"] == 0.3


def test_wires_into_llm_prompt_rewriter(tmp_path: Path) -> None:
    """The canonical teacher path: LLMPromptRewriter uses OpencodeMutatorClient."""
    runner = _FakeRunner("rewritten by teacher")
    client = OpencodeMutatorClient(workspace=tmp_path, runner=runner)
    mutator = LLMPromptRewriter(guidance="improve")
    version = ComponentVersion.of(
        component_id="a", kind="agent",
        definition={"name": "a", "system_prompt": "original prompt"},
    )
    ctx = MutationContext(llm=client)
    out = mutator.mutate(version, ctx)
    assert out is not None
    assert out.definition["system_prompt"] == "rewritten by teacher"


def test_no_raw_http_imports_in_module() -> None:
    """Structural guard: the teacher module imports no HTTP client at all.

    (Endpoint-URL detection is the job of the AST guard test in
    open_agent_compiler/testing/provider_guard.py, which scans call sites rather than docstrings.)
    """
    import ast

    tree = ast.parse(
        Path("open_agent_compiler/improvement/mutators/opencode_teacher.py").read_text()
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "httpx" not in imported
    assert "requests" not in imported
    assert "urllib" not in imported
