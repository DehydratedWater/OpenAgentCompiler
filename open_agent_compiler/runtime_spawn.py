"""SpawnAgentTool — a ScriptTool that spawns a new opencode agent.

Formalises the [agent 1] → tool → [agent 2] composition pattern.
The parent agent calls the tool with `(agent_name, prompt, context)`;
the tool shells out to `opencode_manager.py run --agent ...` and
returns a TaskHandle (when spawn_async=True) or the captured output
(when spawn_async=False).

The bash form already works today via the SECURITY POLICY block
(see compile_permissions for the bash allowlist). This module is
the *Python-typed* surface so:
- Other Python code (FastAPI routes, cron drivers, tests) can spawn
  agents through the same code path with strong typing.
- A ScriptTool subclass embeds it as a json-schema tool, giving
  models that prefer structured tool calls (vs bash) the same
  capability.
- The TaskHandle return shape lets callers poll long-running spawned
  agents without blocking.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from open_agent_compiler.model.core.task_model import TaskHandle
from open_agent_compiler.runtime import ScriptTool


class SpawnAgentInput(BaseModel):
    """Args passed to SpawnAgentTool.execute()."""

    agent_name: str = Field(
        description="Compiled agent identifier (matches a file under build/.opencode/agents/).",
    )
    prompt: str = Field(description="User-style prompt for the spawned agent.")
    context: dict[str, str] | None = Field(
        default=None,
        description=(
            "Free-form key/value pairs surfaced to the spawned agent as"
            " OAC_CTX_<KEY> environment variables. Mirrors the cron-event"
            " context plumbing — keep values short, opaque strings."
        ),
    )
    spawn_async: bool = Field(
        default=False,
        description=(
            "False (default): block until the spawned agent finishes;"
            " result.task.status will be terminal. True: return"
            " immediately with status='running'; the parent agent or"
            " a downstream poller drains via /runs/{run_id}/await."
        ),
    )
    timeout_s: float = Field(
        default=120.0,
        description="Blocking timeout when spawn_async=False.",
    )


class SpawnAgentOutput(BaseModel):
    """Return value from SpawnAgentTool.execute()."""

    task: TaskHandle
    stdout: str = ""
    stderr: str = ""


class SpawnAgentTool(ScriptTool[SpawnAgentInput, SpawnAgentOutput]):
    """Spawn a new opencode agent and return a TaskHandle.

    Encapsulates `uv run scripts/opencode_manager.py run --agent ...`
    behind a typed input/output schema so the dispatch pattern is:

      1. Discoverable to models via the json-schema tool block.
      2. Testable via the standard ScriptTool mock path.
      3. Composable — callers can spawn N agents in parallel by
         invoking N times with spawn_async=True, then awaiting
         each TaskHandle.run_id at /runs/{run_id}/await.

    The compiled agent does NOT need to set up opencode_manager bash
    permissions when invoking this tool through the json-schema
    contract — the parent process runs the opencode_manager script
    directly. Both contracts work; pick per agent.
    """

    name: ClassVar[str] = "spawn_agent"
    description: ClassVar[str] = (
        "Spawn a new opencode agent with the given prompt and return"
        " a TaskHandle. Use for long-running or parallelisable work"
        " that should run in its own session, not as a Task-tool"
        " subagent. spawn_async=True returns immediately."
    )

    def execute(
        self, input: SpawnAgentInput,
        resources=None,
    ) -> SpawnAgentOutput:
        run_id = f"spawn_{uuid.uuid4().hex[:12]}"
        # Resolve the bundled opencode_manager.py — look upward from
        # the script's CWD (Project layouts conventionally have it
        # at <root>/scripts/opencode_manager.py per the scaffold +
        # the build pipeline's auto-include path).
        manager_path = _resolve_manager()
        if manager_path is None:
            return SpawnAgentOutput(
                task=TaskHandle(
                    run_id=run_id, kind="spawned_agent",
                    status="failure",
                    error_message=(
                        "scripts/opencode_manager.py not found — "
                        "compile the project first or run from the repo root"
                    ),
                ),
            )

        env = os.environ.copy()
        for k, v in (input.context or {}).items():
            env[f"OAC_CTX_{k.upper()}"] = str(v)

        if input.spawn_async:
            return self._spawn_detached(input, env, run_id, manager_path)
        return self._spawn_blocking(input, env, run_id, manager_path)

    def _spawn_blocking(
        self, input: SpawnAgentInput, env: dict[str, str],
        run_id: str, manager_path: Path,
    ) -> SpawnAgentOutput:
        cmd = [
            "uv", "run", str(manager_path), "run",
            "--agent", input.agent_name, input.prompt,
        ]
        try:
            proc = subprocess.run(
                cmd, env=env, capture_output=True, text=True,
                timeout=input.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return SpawnAgentOutput(
                task=TaskHandle(
                    run_id=run_id, kind="spawned_agent",
                    status="timeout",
                    error_message=f"spawn exceeded {input.timeout_s}s",
                ),
            )
        except FileNotFoundError as exc:
            return SpawnAgentOutput(
                task=TaskHandle(
                    run_id=run_id, kind="spawned_agent",
                    status="failure",
                    error_message=f"subprocess could not start: {exc}",
                ),
            )
        status = "success" if proc.returncode == 0 else "failure"
        return SpawnAgentOutput(
            task=TaskHandle(
                run_id=run_id, kind="spawned_agent",
                status=status,
                result={"return_code": proc.returncode},
                error_message=proc.stderr if status == "failure" else None,
            ),
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def _spawn_detached(
        self, input: SpawnAgentInput, env: dict[str, str],
        run_id: str, manager_path: Path,
    ) -> SpawnAgentOutput:
        cmd = [
            "uv", "run", str(manager_path), "run",
            "--agent", input.agent_name, input.prompt,
        ]
        try:
            subprocess.Popen(  # noqa: S603 - intentional spawn
                cmd, env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            return SpawnAgentOutput(
                task=TaskHandle(
                    run_id=run_id, kind="spawned_agent",
                    status="failure",
                    error_message=f"subprocess could not start: {exc}",
                ),
            )
        return SpawnAgentOutput(
            task=TaskHandle(
                run_id=run_id, kind="spawned_agent",
                status="running",
                poll_url=f"/runs/{run_id}/await",
            ),
        )


def _resolve_manager() -> Path | None:
    """Walk upward from CWD looking for scripts/opencode_manager.py."""
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        candidate = parent / "scripts" / "opencode_manager.py"
        if candidate.exists():
            return candidate
    return None


if __name__ == "__main__":  # pragma: no cover
    SpawnAgentTool.run()
