"""`oac init` — scaffold a new project."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from open_agent_compiler.scaffold.config import ScaffoldConfig
from open_agent_compiler.scaffold.engine import ScaffoldEngine


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("init", help="Scaffold a new oac project.")
    p.add_argument(
        "target", type=Path,
        help="Directory to scaffold into (created if missing).",
    )
    p.add_argument(
        "-i", "--interactive", action="store_true",
        help=(
            "Walk through scaffold options interactively (humans). Without"
            " this flag, init runs purely from CLI flags (agents / CI)."
        ),
    )
    p.add_argument(
        "--name", default=None,
        help="Project name (default: target directory name).",
    )
    p.add_argument(
        "--template",
        choices=["barebones", "web", "full", "saas-personalized"],
        default="web",
        help="Scaffold shape: barebones=compile+CLI only; web=+FastAPI;"
        " full=+telegram bot + DB; saas-personalized=per-client"
        " auto-optimization SaaS (FastAPI intake/personalize/serve +"
        " personalization module + mocked per-client tests).",
    )
    p.add_argument(
        "--llm",
        choices=["anthropic", "openai", "openrouter", "vllm", "zai-coding-plan"],
        default="anthropic",
    )
    p.add_argument("--with-postgres", action="store_true")
    p.add_argument(
        "--with-sqlite", action="store_true",
        help=(
            "Generate a SQLite-backed notes-db ScriptTool + matching"
            " AccessProfile (prod = file-based, ci = in-memory)."
        ),
    )
    p.add_argument(
        "--with-mcp-server", action="store_true",
        help=(
            "Expose the compiled agents as MCP tools alongside the"
            " FastAPI REST API (generates app/mcp_server.py +"
            " mcp_server_run.py). Requires --template=web or full."
        ),
    )
    p.add_argument("--with-redis", action="store_true")
    p.add_argument("--with-qdrant", action="store_true")
    p.add_argument("--with-ollama", action="store_true")
    p.add_argument("--with-telegram-bot", action="store_true")
    p.add_argument(
        "--observability",
        choices=["none", "langfuse"], default="none",
    )
    p.add_argument(
        "--proxy", choices=["none", "nginx", "traefik"], default="none",
    )
    p.add_argument("--with-cron", action="store_true")
    p.add_argument(
        "--cron-events", type=Path, default=Path("cron/events.json"),
        help="Path (relative to project) where cron events JSON lives.",
    )
    p.add_argument(
        "--force-overwrite", action="store_true",
        help=(
            "Refresh framework-owned files (matched against the"
            " .oac/scaffold-state.json manifest). User-edited files"
            " are PRESERVED. Use this to pick up framework fixes"
            " without losing your registry.py / pyproject.toml /"
            " .env.example customisations."
        ),
    )
    p.add_argument(
        "--force-overwrite-all", action="store_true",
        help=(
            "Nuke EVERY scaffold file unconditionally, including"
            " user-edited ones. Use only when you really want to"
            " reset to defaults — destructive."
        ),
    )
    p.add_argument(
        "--no-uv-sync", dest="uv_sync", action="store_false",
        default=True,
        help=(
            "Skip the post-scaffold `uv sync` step. By default init runs"
            " `uv sync` in the target directory so deps install"
            " immediately (skipped silently when uv isn't on PATH)."
        ),
    )
    p.add_argument(
        "--skills", default="",
        help=(
            "Comma-separated dialect list for developer skills. Subset of"
            " 'opencode,claude'. Empty = no skills emitted. Example:"
            " --skills opencode,claude"
        ),
    )
    p.add_argument(
        "--dialect", default="opencode",
        help=(
            "Output dialect the generated build_agents.py compiles to"
            " (default: opencode). Run `oac info --dialects` to list"
            " registered dialects."
        ),
    )


def _parse_skills(value: str) -> tuple[str, ...]:
    if not value or value.lower() == "none":
        return ()
    skills = tuple(s.strip() for s in value.split(",") if s.strip())
    unknown = [s for s in skills if s not in ("opencode", "claude")]
    if unknown:
        raise ValueError(
            f"unknown skill dialects: {unknown}. Valid: 'opencode', 'claude'."
        )
    return skills


# ---- Interactive prompts -------------------------------------------------


def _prompt(question: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    try:
        answer = input(f"{question}{suffix}: ").strip()
    except EOFError:
        answer = ""
    if not answer and default is not None:
        return default
    return answer


def _prompt_choice(
    question: str, choices: list[str], default: str,
) -> str:
    while True:
        opts = "/".join(c + ("*" if c == default else "") for c in choices)
        ans = _prompt(f"{question} ({opts})", default)
        if ans in choices:
            return ans
        print(f"  → must be one of {choices}; got {ans!r}")


def _prompt_bool(question: str, default: bool = False) -> bool:
    default_str = "y" if default else "n"
    ans = _prompt(f"{question} (y/n)", default_str).lower()
    return ans in ("y", "yes", "true", "1")


def _apply_interactive(args: argparse.Namespace) -> None:
    """Walk the user through every scaffold option; mutate args in place.

    Each prompt's default is the value already on args, so an
    interactive run that just hits Enter at every prompt produces
    the same scaffold as a non-interactive run with no flags.
    """
    print("oac init — interactive mode. Press Enter to accept the default.\n")
    args.name = _prompt("project name", args.name or args.target.name)
    args.template = _prompt_choice(
        "template", ["barebones", "web", "full", "saas-personalized"],
        args.template,
    )
    args.llm = _prompt_choice(
        "llm provider",
        ["anthropic", "openai", "openrouter", "vllm", "zai-coding-plan"],
        args.llm,
    )
    from open_agent_compiler.compiler.dialects.registry import list_dialects

    args.dialect = _prompt_choice(
        "output dialect", list_dialects(), args.dialect,
    )
    if args.template in ("web", "full"):
        print("\n-- service add-ons --")
        args.with_postgres = _prompt_bool(
            "  postgres + pgvector + alembic seed migration",
            args.with_postgres or args.template == "full",
        )
        args.with_mcp_server = _prompt_bool(
            "  expose agents over MCP alongside FastAPI", args.with_mcp_server,
        )
        args.with_redis = _prompt_bool("  redis", args.with_redis)
        args.with_telegram_bot = _prompt_bool(
            "  telegram bot service", args.with_telegram_bot,
        )
        args.with_cron = _prompt_bool("  cron driver", args.with_cron)
    print("\n-- developer extras --")
    args.with_sqlite = _prompt_bool(
        "  starter SQLite-backed notes tool + AccessProfile",
        args.with_sqlite,
    )
    args.skills = _prompt(
        "  developer skills (comma-separated; opencode,claude or empty)",
        args.skills or "opencode,claude",
    )
    args.uv_sync = _prompt_bool(
        "  run `uv sync` after scaffolding", args.uv_sync,
    )
    print()


def handle(
    args: argparse.Namespace,
    load_factory: Callable[[str], Callable[[], Any]],
) -> int:
    if getattr(args, "interactive", False):
        _apply_interactive(args)
    name = args.name or args.target.name or "oac-project"
    from open_agent_compiler.compiler.dialects.registry import list_dialects

    dialect = getattr(args, "dialect", "opencode")
    if dialect not in list_dialects():
        raise ValueError(
            f"unknown dialect {dialect!r}; registered: {list_dialects()}"
        )
    config = ScaffoldConfig(
        target=args.target,
        project_name=name,
        template=args.template,
        llm=args.llm,
        dialect=dialect,
        with_postgres=args.with_postgres,
        with_sqlite=args.with_sqlite,
        with_mcp_server=args.with_mcp_server,
        with_redis=args.with_redis,
        with_qdrant=args.with_qdrant,
        with_ollama=args.with_ollama,
        observability=args.observability,
        proxy=args.proxy,
        with_telegram_bot=args.with_telegram_bot,
        with_cron=args.with_cron,
        cron_events_path=args.cron_events,
        force_overwrite=args.force_overwrite,
        force_overwrite_all=getattr(args, "force_overwrite_all", False),
        skills=_parse_skills(args.skills),
        uv_sync=args.uv_sync,
    )
    engine = ScaffoldEngine(config=config)
    result = engine.render()
    print(
        f"oac init: scaffolded {len(result.written_files)} file(s) into"
        f" {result.target}"
    )
    if result.skipped_existing:
        print(
            f"  (skipped {len(result.skipped_existing)} existing file(s);"
            f" pass --force-overwrite to replace)"
        )
    if result.preserved_user_files:
        print(
            f"  preserved {len(result.preserved_user_files)} user-edited file(s):"
        )
        for p in result.preserved_user_files[:10]:
            print(f"    • {p.relative_to(args.target)}")
        if len(result.preserved_user_files) > 10:
            print(f"    … +{len(result.preserved_user_files) - 10} more")
        print(
            "  (these were NOT overwritten; pass --force-overwrite-all"
            " if you really want to reset them to defaults)"
        )
    if result.skill_files:
        print(
            f"  emitted {len(result.skill_files)} skill file(s) for: "
            f"{', '.join(config.skills)}"
        )
    if result.uv_sync_status == "success":
        print("  ran `uv sync` — dependencies installed.")
    elif result.uv_sync_status == "uv_missing":
        print(
            "  (uv not found on PATH — install it then run `uv sync`"
            f" inside {result.target} to finish setup)"
        )
    elif result.uv_sync_status.startswith("failed"):
        print(
            f"  `uv sync` failed ({result.uv_sync_status}); the project"
            " is fully written but you'll need to resolve the issue and"
            " re-run sync manually."
        )
    elif result.uv_sync_status == "not_attempted":
        print(
            "  --no-uv-sync was set — run `uv sync` manually when ready."
        )
    return 0
