"""Compile the exploration orchestrator for pi runtime."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

from agents import registry  # noqa: E402
from open_agent_compiler.compiler.script import CompileScript  # noqa: E402


def main() -> None:
    script = CompileScript(
        target=HERE / "build",
        factory=registry,
        config="prod",
        dialect="pi",
        clean=True,
        verbose=True,
    )
    result = script.run()
    print(f"wrote {len(result.written_files)} file(s); slots: {result.resolved_slots}")
    for p in sorted(result.written_files):
        print(f"  - {p.relative_to(result.target.parent)}")


if __name__ == "__main__":
    main()
