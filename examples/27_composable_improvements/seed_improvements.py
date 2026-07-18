"""Populate `.oac/promoted/` with three independent example snapshots.

Real users would get these by running `oac improve` against each
component's evaluator + criterion and then `oac promote` the
winners. This script fakes the end state so the reader can see the
plumbing without waiting on real optimisation loops.

The three independent snapshots demonstrate the mix-and-match
promise: each component carries its own improvement; the registry's
`register_with_improvements` walks the tree, applies each
independently, and the compiled output reflects whichever subset has
been promoted.

Re-run safe: clears `.oac/promoted/` before re-seeding so the example
always demonstrates the latest seed values.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from open_agent_compiler.improvement.snapshot import promote, write_snapshot  # noqa: E402
from open_agent_compiler.improvement.version import ComponentVersion  # noqa: E402


def _seed_one(
    component_id: str,
    kind: str,
    definition: dict,
    snap_root: Path,
) -> Path:
    """Write a snapshot then promote it into HERE/.oac/promoted/."""
    version = ComponentVersion.of(
        component_id=component_id, kind=kind,
        definition=definition,
        metrics={"pass_rate": 1.0, "score": 1.0},
    )
    snap_path = write_snapshot(version, snap_root)
    return promote(snap_path, HERE, force=True)


def main() -> None:
    promoted = HERE / ".oac" / "promoted"
    if promoted.exists():
        shutil.rmtree(promoted)
    with tempfile.TemporaryDirectory() as td:
        snap_root = Path(td)

        # 1. Agent prompt — pretend a loop tuned the system_prompt for
        #    a more thorough response.
        agent_dest = _seed_one(
            component_id="time-explainer", kind="agent",
            definition={
                "system_prompt": (
                    "You answer time-related questions precisely. Always"
                    " call the time-tool, cite the timezone returned, and"
                    " explain in 2-3 sentences. Never invent a time."
                ),
            },
            snap_root=snap_root,
        )

        # 2. Tool description + rules — pretend a loop tuned the
        #    description to be sharper + added a clarification rule.
        tool_dest = _seed_one(
            component_id="time-tool", kind="tool",
            definition={
                "description": (
                    "Return the current time as ISO-8601 with explicit"
                    " timezone offset (hours from UTC)."
                ),
                "rules": [
                    "Always include the timezone offset in the response.",
                    "Default to UTC (timezone_hours=0) when no zone given.",
                    "Pass an integer for timezone_hours, never a string.",
                ],
            },
            snap_root=snap_root,
        )

        # 3. Skill — pretend a loop tuned the description, the
        #    long-form usage explanation (which is what the compiled
        #    agent renders as the skill section body), and the rules.
        skill_dest = _seed_one(
            component_id="time-awareness", kind="skill",
            definition={
                "description": (
                    "Pulls the current time from a deterministic script"
                    " and reports it with explicit timezone."
                ),
                "usage_explanation_long": (
                    "When the user asks anything time-related, call the"
                    " time-tool, read its `iso` field, and cite the"
                    " returned timezone explicitly. Never paraphrase the"
                    " timezone — quote it as the tool returned it."
                ),
                "rules": [
                    "Always cite the timezone returned by the tool.",
                    "Never invent a time; always call the tool.",
                ],
            },
            snap_root=snap_root,
        )

    print("Promoted three independent improvements:")
    print(f"  agent prompt → {agent_dest.relative_to(HERE)}")
    print(f"  tool        → {tool_dest.relative_to(HERE)}")
    print(f"  skill       → {skill_dest.relative_to(HERE)}")
    print()
    print(
        "Now run `uv run python examples/27_composable_improvements/agents.py`"
        " to see the registry build with all three merged."
    )


if __name__ == "__main__":
    main()
