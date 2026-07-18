"""ScaffoldEngine end-to-end + per-generator content checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.scaffold.config import ScaffoldConfig
from open_agent_compiler.scaffold.engine import ScaffoldEngine
from open_agent_compiler.scaffold.files import env_example, gitignore, pyproject, readme


def _config(target: Path, **kw) -> ScaffoldConfig:
    return ScaffoldConfig(target=target, **kw)


# ---- config validation ---------------------------------------------------


def test_project_name_validator_rejects_spaces(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid characters"):
        ScaffoldConfig(target=tmp_path, project_name="my project")


def test_full_template_auto_enables_postgres(tmp_path: Path) -> None:
    cfg = ScaffoldConfig(target=tmp_path, template="full")
    assert cfg.with_postgres is True


# ---- gitignore ----------------------------------------------------------


def test_gitignore_includes_oac_paths(tmp_path: Path) -> None:
    out = gitignore.render(_config(tmp_path))
    assert ".oac/" in out
    assert ".opencode/data/" in out
    assert ".env" in out
    assert ".venv/" in out


def test_gitignore_adds_cron_state_when_cron_enabled(tmp_path: Path) -> None:
    out = gitignore.render(_config(tmp_path, with_cron=True))
    assert "cron/state/" in out


# ---- env example -------------------------------------------------------


def test_env_includes_anthropic_block_by_default(tmp_path: Path) -> None:
    out = env_example.render(_config(tmp_path))
    assert "ANTHROPIC_API_KEY" in out


def test_env_swaps_provider_block(tmp_path: Path) -> None:
    out = env_example.render(_config(tmp_path, llm="openrouter"))
    assert "OPENROUTER_API_KEY" in out
    assert "ANTHROPIC_API_KEY" not in out


def test_env_includes_postgres_when_enabled(tmp_path: Path) -> None:
    out = env_example.render(_config(tmp_path, with_postgres=True))
    assert "DATABASE_URL=postgresql+asyncpg" in out


def test_env_includes_cron_events_path(tmp_path: Path) -> None:
    out = env_example.render(_config(
        tmp_path, with_cron=True, cron_events_path=Path("ops/events.json"),
    ))
    assert "CRON_EVENTS=ops/events.json" in out


def test_env_skips_telegram_block_when_disabled(tmp_path: Path) -> None:
    out = env_example.render(_config(tmp_path))
    assert "BOT_TOKEN" not in out


# ---- pyproject ----------------------------------------------------------


def test_pyproject_pins_anthropic_when_llm_is_anthropic(tmp_path: Path) -> None:
    out = pyproject.render(_config(tmp_path, llm="anthropic"))
    assert '"anthropic>=' in out


def test_pyproject_uses_openai_sdk_for_openrouter(tmp_path: Path) -> None:
    out = pyproject.render(_config(tmp_path, llm="openrouter"))
    assert '"openai>=' in out


def test_pyproject_includes_fastapi_for_web_template(tmp_path: Path) -> None:
    out = pyproject.render(_config(tmp_path, template="web"))
    assert '"fastapi>=' in out
    assert '"uvicorn[standard]>=' in out


def test_pyproject_full_template_adds_db_libs(tmp_path: Path) -> None:
    out = pyproject.render(_config(tmp_path, template="full"))
    assert '"sqlalchemy[asyncio]>=' in out
    assert '"asyncpg>=' in out
    assert '"alembic>=' in out


def test_pyproject_includes_langfuse_when_observability_set(tmp_path: Path) -> None:
    out = pyproject.render(_config(tmp_path, observability="langfuse"))
    assert '"langfuse>=' in out


# ---- README -------------------------------------------------------------


def test_readme_mentions_template_and_project_name(tmp_path: Path) -> None:
    out = readme.render(_config(tmp_path, project_name="my-proj", template="web"))
    assert "# my-proj" in out
    assert "--template=web" in out


# ---- engine integration ------------------------------------------------


def test_engine_writes_expected_files_into_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    result = ScaffoldEngine(config=_config(target, project_name="proj")).render()
    written = {p.relative_to(target).as_posix() for p in result.written_files}
    assert ".gitignore" in written
    assert ".env.example" in written
    assert "pyproject.toml" in written
    assert "README.md" in written
    assert "agents/__init__.py" in written
    assert "agents/registry.py" in written
    assert "build_agents.py" in written


def test_engine_refuses_non_empty_target_without_force(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    (target / "marker.txt").write_text("hi")
    with pytest.raises(ValueError, match="not empty"):
        ScaffoldEngine(config=_config(target, project_name="proj")).render()


def test_engine_skips_existing_files_under_default_settings(tmp_path: Path) -> None:
    """Phase 38: --force-overwrite preserves orphan files (no manifest entry).

    The destructive 'nuke everything' behaviour now requires
    --force-overwrite-all explicitly. This protects pre-existing
    user files from getting clobbered when the scaffold runs into
    a non-empty directory.
    """
    target = tmp_path / "proj"
    target.mkdir()
    (target / "README.md").write_text("PREEXISTING")
    # --force-overwrite alone preserves orphans.
    cfg = _config(target, project_name="proj", force_overwrite=True)
    result = ScaffoldEngine(config=cfg).render()
    assert (target / "README.md").read_text() == "PREEXISTING"
    assert (target / "README.md") in result.preserved_user_files
    # --force-overwrite-all overrides → file IS rewritten.
    cfg2 = _config(
        target, project_name="proj", force_overwrite_all=True,
    )
    result2 = ScaffoldEngine(config=cfg2).render()
    assert (target / "README.md").read_text() != "PREEXISTING"
    assert any(p.name == "README.md" for p in result2.written_files)


def test_engine_starter_registry_is_valid_python(tmp_path: Path) -> None:
    """The generated registry must at least parse."""
    import ast

    target = tmp_path / "proj"
    ScaffoldEngine(config=_config(target, project_name="proj")).render()
    ast.parse((target / "agents" / "registry.py").read_text())
    ast.parse((target / "build_agents.py").read_text())


def test_cli_init_creates_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from open_agent_compiler.cli.main import main

    target = tmp_path / "proj"
    rc = main([
        "init", str(target),
        "--name", "demo-proj",
        "--template", "barebones",
        "--llm", "anthropic",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "scaffolded" in out
    assert (target / ".env.example").exists()
    assert (target / "agents" / "registry.py").exists()


# ---- Phase 14: with_sqlite ------------------------------------------


def test_with_sqlite_emits_notes_db_tool_and_access_profile(
    tmp_path: Path,
) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="barebones",
        llm="anthropic", with_sqlite=True,
    )).render()
    assert (tmp_path / "tools" / "notes_db.py").exists()
    assert (tmp_path / "agents" / "access_profile.py").exists()


def test_with_sqlite_tool_uses_resources_signature(tmp_path: Path) -> None:
    """Generated tool's execute() declares the (input, resources) shape."""
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="barebones",
        llm="anthropic", with_sqlite=True,
    )).render()
    src = (tmp_path / "tools" / "notes_db.py").read_text()
    assert "resources: dict" in src
    assert "sqlite_connect()" in src


def test_with_sqlite_tool_is_valid_python(tmp_path: Path) -> None:
    """Generated SQLite tool parses (catches syntax regressions)."""
    import ast
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="barebones",
        llm="anthropic", with_sqlite=True,
    )).render()
    ast.parse((tmp_path / "tools" / "notes_db.py").read_text())
    ast.parse((tmp_path / "agents" / "access_profile.py").read_text())


def test_with_sqlite_access_profile_binds_notes_db(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="barebones",
        llm="anthropic", with_sqlite=True,
    )).render()
    src = (tmp_path / "agents" / "access_profile.py").read_text()
    assert "AccessProfile" in src
    assert "ResourceBinding" in src
    assert "notes_db" in src
    # Both prod (file-based) and ci (in-memory) profiles.
    assert ":memory:" in src


def test_with_sqlite_disabled_does_not_emit_notes_db(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="bare", template="barebones",
        llm="anthropic",
    )).render()
    assert not (tmp_path / "tools" / "notes_db.py").exists()
    assert not (tmp_path / "agents" / "access_profile.py").exists()


def test_scaffold_registry_uses_register_with_improvements(
    tmp_path: Path,
) -> None:
    """New projects ship with the Phase-10 surface enabled by default."""
    ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="barebones", llm="anthropic",
    )).render()
    src = (tmp_path / "agents" / "registry.py").read_text()
    assert "register_with_improvements" in src
    assert "project_root=PROJECT_ROOT" in src


def test_scaffold_readme_includes_improve_runbook(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="barebones", llm="anthropic",
    )).render()
    src = (tmp_path / "README.md").read_text()
    assert "oac improve" in src
    assert "oac promote" in src
    # No stale "Phase 6, future" language.
    assert "Phase 6, future" not in src


# ---- Phase 17: pgvector + Alembic scaffolding -----------------------


def test_with_postgres_emits_db_session_module(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    src = (tmp_path / "db" / "session.py").read_text()
    assert "AsyncSession" in src
    assert "async_sessionmaker" in src
    assert "get_database_url" in src
    assert "session_scope" in src


def test_with_postgres_emits_alembic_env(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    env = (tmp_path / "migrations" / "env.py").read_text()
    assert "async_engine_from_config" in env
    assert "from db.session import get_database_url" in env
    assert "run_migrations_offline" in env
    assert "run_migrations_online" in env


def test_with_postgres_emits_seed_migration_with_pgvector(
    tmp_path: Path,
) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    seed = (tmp_path / "migrations" / "versions" / "001_initial.py").read_text()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in seed
    assert "CREATE TABLE IF NOT EXISTS runs" in seed
    assert "CREATE TABLE IF NOT EXISTS tool_calls" in seed
    # run_id FK + cascade so tool_calls clean up with their parent run.
    assert "ON DELETE CASCADE" in seed


def test_with_postgres_emits_alembic_ini(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    ini = (tmp_path / "alembic.ini").read_text()
    assert "[alembic]" in ini
    assert "script_location = migrations" in ini


def test_with_postgres_emits_repositories_module(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    src = (tmp_path / "db" / "repositories.py").read_text()
    assert "create_run" in src
    assert "record_tool_call" in src
    assert "tool_failure_rate" in src
    assert "list_runs" in src
    assert "get_run_detail" in src


def test_alembic_seed_migration_is_valid_python(tmp_path: Path) -> None:
    import ast
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    ast.parse(
        (tmp_path / "migrations" / "versions" / "001_initial.py").read_text(),
    )
    ast.parse((tmp_path / "db" / "session.py").read_text())
    ast.parse((tmp_path / "db" / "repositories.py").read_text())
    ast.parse((tmp_path / "migrations" / "env.py").read_text())


def test_without_postgres_does_not_emit_db_or_migrations(
    tmp_path: Path,
) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="barebones",
        llm="anthropic",
    )).render()
    assert not (tmp_path / "db" / "session.py").exists()
    assert not (tmp_path / "migrations").exists()
    assert not (tmp_path / "alembic.ini").exists()


# ---- Phase 18: Run-tracking service ---------------------------------


def test_with_postgres_full_template_emits_runs_router(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    runs = (tmp_path / "app" / "runs.py").read_text()
    assert "router = APIRouter()" in runs
    assert "/runs" in runs
    assert "/metrics/tool-failures" in runs
    assert "tool_failure_rate" in runs


def test_with_postgres_full_template_emits_persistence_wrapper(
    tmp_path: Path,
) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    persistence = (tmp_path / "app" / "persistence.py").read_text()
    assert "record_run" in persistence
    assert "create_run" in persistence
    assert "complete_run" in persistence
    assert "mark_run_running" in persistence


def test_with_postgres_full_template_app_main_includes_runs_router(
    tmp_path: Path,
) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    main = (tmp_path / "app" / "main.py").read_text()
    assert "from app.persistence import record_run" in main
    assert "from app.runs import router as runs_router" in main
    assert "app.include_router(runs_router)" in main
    # Phase 23: dispatcher wraps run_agent + record_run.
    assert "dispatch_run(name, req, run_agent" in main
    assert "with_persistence=True" in main


def test_without_postgres_app_main_skips_persistence(
    tmp_path: Path,
) -> None:
    """Web template *without* postgres → no DB imports in app/main."""
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="web", llm="anthropic",
    )).render()
    main = (tmp_path / "app" / "main.py").read_text()
    # Phase 23: still goes through dispatch_run, but with persistence
    # disabled (no DB).
    assert "from app.persistence import record_run" not in main
    assert "runs_router" not in main
    assert "dispatch_run(name, req, run_agent" in main
    assert "with_persistence=False" in main


def test_runs_router_and_persistence_are_valid_python(tmp_path: Path) -> None:
    import ast
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    ast.parse((tmp_path / "app" / "runs.py").read_text())
    ast.parse((tmp_path / "app" / "persistence.py").read_text())
    # And the modified app/main parses too.
    ast.parse((tmp_path / "app" / "main.py").read_text())


# ---- Phase 20: long-running task primitives in the scaffold ---------


def test_runs_router_exposes_await_endpoint(tmp_path: Path) -> None:
    """Phase 20: scaffold ships /runs/{run_id}/await for long-polling."""
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    src = (tmp_path / "app" / "runs.py").read_text()
    assert "/runs/{run_id}/await" in src
    assert "timeout_s" in src
    assert "poll_interval_s" in src
    # Returns the `awaited` flag so callers can distinguish completion
    # from a timeout.
    assert '"awaited"' in src


def test_phase19_context_volatility_endpoint_still_present(
    tmp_path: Path,
) -> None:
    """Belt-and-braces — Phase 19's endpoint coexists with Phase 20's."""
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    src = (tmp_path / "app" / "runs.py").read_text()
    assert "/metrics/context-volatility" in src
    assert "/metrics/tool-failures" in src
    assert "/runs/{run_id}/await" in src


# ---- Phase 23: three calling modes + variant + retry policy --------


def test_phase23_models_include_run_mode_and_retry_policy(
    tmp_path: Path,
) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="full", llm="anthropic",
    )).render()
    src = (tmp_path / "app" / "models.py").read_text()
    # RunMode literal with all three patterns.
    assert "'sync'" in src
    assert "'async'" in src
    assert "'fire_and_forget'" in src
    # RetryPolicy + RetryStep + RetryTrigger.
    assert "class RetryPolicy" in src
    assert "class RetryStep" in src
    assert "RetryTrigger" in src
    # AgentRunRequest carries mode + variant + retry + callback_url.
    assert "mode: RunMode" in src
    assert "variant: str | None" in src
    assert "retry: RetryPolicy | None" in src
    assert "callback_url: str | None" in src
    # AgentRunResult carries resolved_variant + fallback_chain.
    assert "resolved_variant: str | None" in src
    assert "fallback_chain: list[dict" in src


def test_phase23_dispatch_module_branches_on_mode_and_retries(
    tmp_path: Path,
) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="full", llm="anthropic",
    )).render()
    src = (tmp_path / "app" / "dispatch.py").read_text()
    assert "async def dispatch_run" in src
    assert "_execute_with_retry" in src
    assert "_step_applies" in src
    # Callback POST path lives in here too.
    assert "callback_url" in src
    assert "urllib.request" in src


def test_phase23_app_main_uses_dispatch_run(tmp_path: Path) -> None:
    """Phase 23 routes go through dispatch_run, not run_agent directly."""
    ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="full", llm="anthropic",
    )).render()
    main = (tmp_path / "app" / "main.py").read_text()
    assert "from app.dispatch import dispatch_run" in main
    assert "dispatch_run(name, req, run_agent" in main


def test_phase23_variant_resolution_uses_resolved_filename(
    tmp_path: Path,
) -> None:
    """The runner cmd passes the resolved file's path-stem to opencode."""
    ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="full", llm="anthropic",
    )).render()
    runner = (tmp_path / "app" / "agent_runner.py").read_text()
    # _resolve_agent_md returns (path, resolved_variant) — both used.
    assert "resolved_variant" in runner
    assert "effective_agent = rel.as_posix().removesuffix('.md')" in runner


def test_phase23_dispatch_and_main_are_valid_python(tmp_path: Path) -> None:
    import ast
    ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="full", llm="anthropic",
    )).render()
    ast.parse((tmp_path / "app" / "dispatch.py").read_text())
    ast.parse((tmp_path / "app" / "models.py").read_text())
    ast.parse((tmp_path / "app" / "main.py").read_text())
    ast.parse((tmp_path / "app" / "agent_runner.py").read_text())


# ---- Phase 24: MCP server scaffold ---------------------------------


def test_with_mcp_server_emits_mcp_module(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full",
        llm="anthropic", with_mcp_server=True,
    )).render()
    mcp_src = (tmp_path / "app" / "mcp_server.py").read_text()
    assert "from mcp.server.fastmcp import FastMCP" in mcp_src
    assert "FastMCP(" in mcp_src
    assert "register_all_agents" in mcp_src
    assert "dispatch_run" in mcp_src
    # Entry point exists.
    assert (tmp_path / "mcp_server_run.py").exists()
    run_src = (tmp_path / "mcp_server_run.py").read_text()
    assert "server.run()" in run_src


def test_with_mcp_server_adds_mcp_dependency_to_pyproject(
    tmp_path: Path,
) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full",
        llm="anthropic", with_mcp_server=True,
    )).render()
    pyproj = (tmp_path / "pyproject.toml").read_text()
    assert '"mcp>=1.0.0"' in pyproj


def test_without_mcp_server_flag_does_not_emit_module(tmp_path: Path) -> None:
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full", llm="anthropic",
    )).render()
    assert not (tmp_path / "app" / "mcp_server.py").exists()
    assert not (tmp_path / "mcp_server_run.py").exists()
    pyproj = (tmp_path / "pyproject.toml").read_text()
    assert '"mcp' not in pyproj


def test_mcp_server_module_is_valid_python(tmp_path: Path) -> None:
    import ast
    ScaffoldEngine(config=_config(
        tmp_path, project_name="yt", template="full",
        llm="anthropic", with_mcp_server=True,
    )).render()
    ast.parse((tmp_path / "app" / "mcp_server.py").read_text())
    ast.parse((tmp_path / "mcp_server_run.py").read_text())


def test_mcp_server_persistence_flag_matches_postgres_toggle(
    tmp_path: Path,
) -> None:
    """When postgres is on, MCP runs persist; when off, they skip."""
    # With postgres
    (tmp_path / "with_db").mkdir()
    ScaffoldEngine(config=_config(
        tmp_path / "with_db", project_name="x", template="full",
        llm="anthropic", with_mcp_server=True,
    )).render()
    src = (tmp_path / "with_db" / "app" / "mcp_server.py").read_text()
    assert "_WITH_PERSISTENCE: bool = True" in src

    # Without postgres (use web template + explicit no postgres)
    (tmp_path / "no_db").mkdir()
    ScaffoldEngine(config=_config(
        tmp_path / "no_db", project_name="x", template="web",
        llm="anthropic", with_mcp_server=True,
    )).render()
    src = (tmp_path / "no_db" / "app" / "mcp_server.py").read_text()
    assert "_WITH_PERSISTENCE: bool = False" in src


# ---- Phase 25: auto uv sync + interactive mode ---------------------


def test_uv_sync_status_reports_uv_missing_when_uv_not_on_path(
    tmp_path: Path, monkeypatch,
) -> None:
    """When uv isn't found, scaffold still completes; status reports it."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="barebones",
        llm="anthropic", uv_sync=True,
    )).render()
    assert result.uv_sync_status == "uv_missing"
    # Files still all there.
    assert (tmp_path / "pyproject.toml").exists()


def test_uv_sync_skipped_when_flag_off(tmp_path: Path) -> None:
    result = ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="barebones",
        llm="anthropic", uv_sync=False,
    )).render()
    assert result.uv_sync_status == "not_attempted"


def test_uv_sync_propagates_subprocess_returncode(
    tmp_path: Path, monkeypatch,
) -> None:
    """Failure exit codes surface as 'failed:<code>' without crashing."""
    import shutil
    import subprocess
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/uv")
    fake = type("Proc", (), {"returncode": 7, "stdout": "", "stderr": "boom"})()
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: fake,
    )
    result = ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="barebones",
        llm="anthropic", uv_sync=True,
    )).render()
    assert result.uv_sync_status == "failed:7"


def test_uv_sync_handles_subprocess_timeout(
    tmp_path: Path, monkeypatch,
) -> None:
    import shutil
    import subprocess
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/uv")
    def _boom(*args, **kw):
        raise subprocess.TimeoutExpired(cmd="uv sync", timeout=600)
    monkeypatch.setattr(subprocess, "run", _boom)
    result = ScaffoldEngine(config=_config(
        tmp_path, project_name="x", template="barebones",
        llm="anthropic", uv_sync=True,
    )).render()
    assert result.uv_sync_status == "failed:timeout"


def test_init_cli_supports_no_uv_sync_flag(
    tmp_path: Path, capsys,
) -> None:
    """`--no-uv-sync` opts out cleanly."""
    from open_agent_compiler.cli.main import main
    target = tmp_path / "p25"
    rc = main([
        "init", str(target),
        "--name", "p25",
        "--template", "barebones",
        "--llm", "anthropic",
        "--no-uv-sync",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "run `uv sync` manually" in out


def test_init_cli_runs_interactive_flow_with_defaults(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """`--interactive` + empty input at every prompt produces a valid project."""
    from open_agent_compiler.cli.main import main
    target = tmp_path / "p25_i"
    # Feed an empty line for every prompt → every default is taken.
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "")
    rc = main([
        "init", str(target),
        "--interactive",
        "--no-uv-sync",  # don't shell out during the test
    ])
    assert rc == 0
    # Defaults give us a web template with FastAPI.
    assert (target / "app" / "main.py").exists()
    assert (target / "pyproject.toml").exists()


# ---- dialect axis --------------------------------------------------------


def test_build_agents_defaults_to_opencode_dialect(tmp_path: Path) -> None:
    from open_agent_compiler.scaffold.files import agents

    out = agents.render_build_agents_script(_config(tmp_path))
    assert 'dialect="opencode"' in out
    assert "./build/.opencode/" in out


def test_build_agents_honors_pi_dialect(tmp_path: Path) -> None:
    from open_agent_compiler.scaffold.files import agents

    out = agents.render_build_agents_script(_config(tmp_path, dialect="pi"))
    assert 'dialect="pi"' in out
    assert "./build/.pi/" in out


# ---- uv sources injection -------------------------------------------------


def test_pyproject_points_uv_sources_at_framework_checkout(tmp_path: Path) -> None:
    """When `oac` runs from a source checkout, scaffolds resolve the
    framework from that checkout instead of the PyPI release."""
    out = pyproject.render(_config(tmp_path))
    assert '"open-agent-compiler>=1.0.0",' in out
    assert "[tool.uv.sources]" in out
    assert "open-agent-compiler = { path = " in out
    assert "editable = true" in out
