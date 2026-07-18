"""Drive `oac init` programmatically with three different shapes.

Generates three full project scaffolds under ./generated/ so a reader
can browse each shape side-by-side. The shapes:

- barebones/   — minimal Python project (no Docker)
- web/         — FastAPI + opencode-web container; no DB
- full/        — telegram bot + Postgres + cron + langfuse + redis

Each generated project includes the developer skill bundles for both
opencode and claude (so a coding agent that opens the scaffold knows
how to work on it).
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
    _scaffold(
        "barebones",
        template="barebones",
        llm="anthropic",
    )
    _scaffold(
        "web-zai",
        template="web",
        llm="zai-coding-plan",
        with_cron=True,
    )
    _scaffold(
        "full-stack",
        template="full",
        llm="zai-coding-plan",
        with_postgres=True,
        with_redis=True,
        with_telegram_bot=True,
        with_cron=True,
        observability="langfuse",
    )
    print(
        f"\nScaffolded 3 projects under {HERE/'generated'}/."
        " Browse each to compare templates."
    )


if __name__ == "__main__":
    main()
