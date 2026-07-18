"""Compile the same agent tree for BOTH opencode and pi runtimes.

Demonstrates that the framework's agent definitions are runtime-agnostic —
the same Python code compiles to:
- `.opencode/agents/*.md` for OpenCode
- `.pi/agents/*.md` for Pi

This is useful for teams that want to test agents in both runtimes or
migrate from one to the other.
"""

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
    # Compile for OpenCode
    opencode_target = HERE / "build_opencode"
    opencode_script = CompileScript(
        target=opencode_target,
        factory=registry,
        config="prod",
        dialect="opencode",
        clean=True,
        verbose=True,
    )
    opencode_result = opencode_script.run()
    print(f"\n[OpenCode] wrote {len(opencode_result.written_files)} file(s)")
    for p in sorted(opencode_result.written_files):
        print(f"  - {p.relative_to(opencode_target.parent)}")

    # Compile for Pi
    pi_target = HERE / "build_pi"
    pi_script = CompileScript(
        target=pi_target,
        factory=registry,
        config="prod",
        dialect="pi",
        clean=True,
        verbose=True,
    )
    pi_result = pi_script.run()
    print(f"\n[Pi] wrote {len(pi_result.written_files)} file(s)")
    for p in sorted(pi_result.written_files):
        print(f"  - {p.relative_to(pi_target.parent)}")

    print("\n✓ Same agent definitions compiled for both runtimes!")


if __name__ == "__main__":
    main()
