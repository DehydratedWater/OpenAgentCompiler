"""Generate the `saas-personalized` template (Phase F) — a worked example.

Drives `oac init --template saas-personalized` programmatically (via the
underlying `ScaffoldEngine`) so a reader can browse the generated per-client
agentic-SaaS starter: a base fleet + built-in tools, a per-client
personalization module (chat→ClientSpec → capability merge → datasource
auto-profile → compile_personalized → PersonalizationRun → per-client
promotions → serve), a FastAPI intake/optimize/serve surface, a CLI, and mocked
per-client tests that ship GREEN.

Generates two variants under ./generated/ so you can compare:
  * zai/      — teacher/judge via the zai-coding-plan provider (the default loop)
  * postgres/ — same, plus the run-tracking DB (--with-postgres) and MCP surface

Nothing is run live: this only writes files. To run the generated tests:
    cd examples/91_saas_personalized/generated/zai
    PYTHONPATH=<repo-root>:. pytest tests/test_personalization.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from open_agent_compiler.scaffold.config import ScaffoldConfig  # noqa: E402
from open_agent_compiler.scaffold.engine import ScaffoldEngine  # noqa: E402


def _scaffold(name: str, **kw) -> None:
    target = HERE / "generated" / name
    if target.exists():
        import shutil
        shutil.rmtree(target)
    config = ScaffoldConfig(
        target=target,
        project_name=name,
        template="saas-personalized",
        force_overwrite=True,
        skills=("opencode", "claude"),
        **kw,
    )
    result = ScaffoldEngine(config=config).render()
    print(
        f"\n{name}: wrote {len(result.written_files)} project file(s)"
        f" + {len(result.skill_files)} skill file(s)"
    )
    for p in sorted(result.written_files):
        print(f"  {p.relative_to(target.parent)}")


def main() -> None:
    _scaffold("zai", llm="zai-coding-plan")
    _scaffold(
        "postgres",
        llm="zai-coding-plan",
        with_postgres=True,
        with_mcp_server=True,
    )
    print(
        f"\nScaffolded 2 saas-personalized projects under {HERE/'generated'}/."
        "\nThe per-client flow: chat→ClientSpec → capability merge →"
        " datasource auto-profile → compile_personalized → PersonalizationRun"
        " (opencode-only) → per-client .oac/promoted/<client_id>/ → serve."
    )


if __name__ == "__main__":
    main()
