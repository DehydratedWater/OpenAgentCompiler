"""Demo of SpawnAgentTool — [agent 1] → tool → [agent 2] composition.

Run with:

    uv run python examples/31_spawn_agent/spawn_demo.py

Two paths shown:
  1. Synchronous spawn — coordinator awaits the worker's output.
  2. Asynchronous spawn — coordinator returns a poll URL and exits;
     the worker keeps running in the background.

The script doesn't actually invoke opencode (no API key required) —
it patches `subprocess.run`/`Popen` so you can see the TaskHandle
shape end-to-end. In a real deployment the patch goes away; the
script just becomes a CLI wrapper for any agent → agent dispatch.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from open_agent_compiler import SpawnAgentInput, SpawnAgentTool  # noqa: E402


def main() -> None:
    # Use an isolated tempdir so the resolver finds a stub
    # `scripts/opencode_manager.py` WITHOUT polluting the repo. In a
    # real project this stub IS the bundled scaffold script and lives
    # next to your build_agents.py.
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "scripts").mkdir()
        (td_path / "scripts" / "opencode_manager.py").write_text(
            "# demo stub — real scripts/opencode_manager.py ships with the scaffold\n"
        )
        prev = Path.cwd()
        os.chdir(td_path)
        try:
            _run_demo()
        finally:
            os.chdir(prev)


def _run_demo() -> None:
    print("=== Synchronous spawn ===\n")
    fake_done = MagicMock(returncode=0, stdout="42", stderr="")
    with patch("subprocess.run", return_value=fake_done):
        out = SpawnAgentTool().execute(SpawnAgentInput(
            agent_name="number-cruncher",
            prompt="What is 6 * 7?",
            context={"user_id": "alice"},
        ))
    print(f"task.status = {out.task.status}")
    print(f"task.run_id = {out.task.run_id}")
    print(f"stdout = {out.stdout!r}")

    print("\n=== Asynchronous spawn ===\n")
    with patch("subprocess.Popen") as mock_popen:
        out = SpawnAgentTool().execute(SpawnAgentInput(
            agent_name="deep-research",
            prompt="Survey papers on X published in 2024",
            spawn_async=True,
            context={"user_id": "alice", "topic": "vector-databases"},
        ))
    print(f"task.status   = {out.task.status}")
    print(f"task.run_id   = {out.task.run_id}")
    print(f"task.poll_url = {out.task.poll_url}")
    print(f"Popen called  = {mock_popen.called}")

    print("\n=== Composition pattern (parent's perspective) ===\n")
    print(
        "  1. Parent agent calls SpawnAgentTool with spawn_async=True\n"
        "     for each leg of a parallel fan-out.\n"
        "  2. Collects N TaskHandle.run_ids back.\n"
        "  3. Drains via N parallel GET /runs/{run_id}/await calls\n"
        "     (FastAPI scaffold's runs router; see Phase 20 example 29).\n"
        "  4. Composes the N spawn outputs into its final reply."
    )


if __name__ == "__main__":
    main()
