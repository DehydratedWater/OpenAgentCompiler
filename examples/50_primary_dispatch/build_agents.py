"""Compile coordinator + worker.

The worker is compiled as a primary agent (not subagent mode) so it
can be invoked via opencode_manager.py from the coordinator. We
override its agent_mode after resolve_config because the registry's
default rule sets non-'primary' slots to subagent mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

from agents import registry  # noqa: E402
from open_agent_compiler.compiler.compile import build  # noqa: E402


def main() -> None:
    reg = registry()
    target = HERE / "build"
    # Wipe target.
    import shutil
    if target.exists():
        shutil.rmtree(target)

    # Resolve the config and override the worker's agent_mode to primary
    # (the default slot→subagent rule would mark it as subagent).
    resolved = reg.resolve_config("prod")
    resolved["number-cruncher"] = resolved["number-cruncher"].model_copy(
        update={"agent_mode": "primary"},
    )

    from open_agent_compiler.compiler.dialects.opencode.compiler import OpenCodeCompiler
    compiler = OpenCodeCompiler(target, resolved)
    compiler.compile()

    written = sorted(p for p in target.rglob("*") if p.is_file())
    print(f"wrote {len(written)} file(s):")
    for p in written:
        print(f"  - {p.relative_to(target.parent)}")


if __name__ == "__main__":
    main()
