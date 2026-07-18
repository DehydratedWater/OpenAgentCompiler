"""Subprocess helpers that invoke `opencode run` for evaluation + mutation.

Two helpers:

- run_candidate_prompt(candidate_md, prompt, model) — writes the
  candidate's prompt as a temp opencode agent, calls opencode, returns
  the response text. Used by the evaluator.
- rewrite_via_opencode(target, guidance, *, model) — implements the
  LLMMutatorClient protocol by calling `opencode run -m <model>` with a
  rewrite prompt. Used by LLMPromptRewriter.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


_OPENCODE = "opencode"


def _env_for(project_dir: Path) -> dict[str, str]:
    """Build the env dict opencode needs.

    opencode reads $PWD (not os.getcwd()) for project discovery; without
    setting it, `subprocess.run(cwd=…)` calls report "Agent not found"
    because the agent search starts from the launching process's PWD.
    """
    return {**os.environ, "PWD": str(project_dir.resolve())}

# A persistent eval workspace under the example dir. opencode behaves
# differently in /tmp/ vs inside a real project (session storage and
# project marker discovery); writing into a stable repo-local path keeps
# it happy.
_HERE = Path(__file__).resolve().parent
_EVAL_WORKSPACE = _HERE / "eval_workspace"


def _parse_opencode_json_stream(stdout: str) -> str:
    """Concatenate the text from every `text` event in opencode's JSON output.

    `opencode run --format json` emits one event per line. Each event is
    a JSON object with a `type` field (step_start, text, step_finish,
    tool_use, …). We only care about `text` events with .part.text.

    When the model has multiple text turns (rare in single-shot run mode),
    they're concatenated in order. No-output / non-JSON lines are skipped
    silently so a stray log line can't poison parsing.
    """
    parts: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "text":
            continue
        text = event.get("part", {}).get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()


def run_compiled_agent(
    project_dir: Path, agent_name: str, prompt: str, *,
    timeout_s: float = 120.0,
) -> str:
    """Invoke a compiled agent via opencode, return the cleaned response.

    Uses `--format json` so the subprocess can parse structured output
    reliably — `opencode run` without --format suppresses output when
    stdout isn't a TTY.
    """
    result = subprocess.run(
        [
            _OPENCODE, "run", "--format", "json",
            "--agent", agent_name, prompt,
        ],
        cwd=str(project_dir),
        env=_env_for(project_dir),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return _parse_opencode_json_stream(result.stdout)


def _write_candidate(system_prompt: str, *, model: str) -> tuple[Path, str]:
    """Write the candidate to the persistent eval workspace.

    Returns (project_dir, agent_name). Overwrites the previous candidate
    on every call so the same opencode session storage is reused —
    opencode behaves erratically in fresh /tmp/ directories.
    """
    agents_dir = _EVAL_WORKSPACE / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_name = "candidate"
    body = (
        "---\n"
        "description: Improvement candidate\n"
        f"model: {model}\n"
        "mode: primary\n"
        "permission:\n"
        "  '*': deny\n"
        "tool:\n"
        "  read: false\n"
        "  write: false\n"
        "  edit: false\n"
        "  task: false\n"
        "  todoread: false\n"
        "  todowrite: false\n"
        "  mcp: false\n"
        "---\n"
        "\n"
        f"# {agent_name}\n"
        "\n"
        f"{system_prompt}\n"
    )
    (agents_dir / f"{agent_name}.md").write_text(body)
    return _EVAL_WORKSPACE, agent_name


def run_candidate_prompt(
    system_prompt: str, user_prompt: str, *, model: str,
    timeout_s: float = 120.0,
) -> str:
    """Write the candidate to the eval workspace and invoke it."""
    project_dir, agent_name = _write_candidate(system_prompt, model=model)
    return run_compiled_agent(
        project_dir, agent_name, user_prompt, timeout_s=timeout_s,
    )


class OpencodeMutatorClient:
    """Implements LLMMutatorClient by calling `opencode run -m <model>`.

    Single-shot rewrite: the prompt template embeds the target text and
    the guidance, asks the optimiser model to return ONLY the rewritten
    text (no preamble), and returns whatever opencode prints.
    """

    def __init__(self, model: str, *, timeout_s: float = 180.0) -> None:
        self.model = model
        self.timeout_s = timeout_s

    def rewrite(
        self, target: str, guidance: str, *,
        context: dict | None = None,
        model: str | None = None,
    ) -> str:
        ctx_block = ""
        if context:
            failures = context.get("failures") or []
            if failures:
                fail_lines = "\n".join(
                    f"- {f}" for f in failures
                )
                ctx_block = (
                    "\n\nThe target failed these checks "
                    "(use them to guide the rewrite):\n"
                    f"{fail_lines}\n"
                )

        prompt = (
            f"{guidance}\n"
            f"{ctx_block}"
            f"\n--- TARGET TEXT ---\n{target}\n---\n"
            "\nRespond with ONLY the rewritten target text. No preamble,"
            " no markdown fences, no commentary."
        )
        # For pure --model invocation (no agent), cwd doesn't matter as
        # much — opencode just spins up its default 'build' agent. Use
        # the eval workspace anyway for session storage consistency.
        result = subprocess.run(
            [
                _OPENCODE, "run", "--format", "json",
                "--model", model or self.model, prompt,
            ],
            cwd=str(_EVAL_WORKSPACE),
            env=_env_for(_EVAL_WORKSPACE),
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
        )
        return _parse_opencode_json_stream(result.stdout)
