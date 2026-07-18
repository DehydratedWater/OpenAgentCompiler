"""Compile the composable-improvements registry.

Mirrors the other examples' build_agents.py shape — the only
difference is that `agents.py` here uses
`register_with_improvements()` so any promoted snapshot under
`.oac/promoted/` is merged transparently before compilation. From
the compiler's perspective there is nothing new: by the time it sees
the AgentDefinition, the auto-improvements have already been
merged.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

from agents import registry  # noqa: E402
from open_agent_compiler.compiler.script import CompileScript  # noqa: E402


def main() -> None:
    script = CompileScript(
        target=HERE / "build",
        factory=registry,
        config="prod",
        clean=True,
        verbose=True,
    )
    result = script.run()
    print(
        "Built composable-improvements demo. Each piece of the tree"
        " (agent prompt, time-tool description+rules, time-awareness"
        " skill description+rules) was loaded from its independently"
        " promoted snapshot when one was present, baseline otherwise."
    )
    print(f"\nwrote {len(result.written_files)} file(s):")
    for p in sorted(result.written_files):
        print(f"  - {p.relative_to(result.target.parent)}")


if __name__ == "__main__":
    main()
