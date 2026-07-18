"""Web template + cron generator tests."""

from __future__ import annotations

import json
from pathlib import Path


from open_agent_compiler.scaffold.config import ScaffoldConfig
from open_agent_compiler.scaffold.engine import ScaffoldEngine
from open_agent_compiler.scaffold.files import compose, cron, dockerfile, app as app_files


def _cfg(target: Path, **kw) -> ScaffoldConfig:
    return ScaffoldConfig(target=target, **kw)


# ---- Dockerfile ----------------------------------------------------------


def test_dockerfile_pins_uv_and_gosu(tmp_path: Path) -> None:
    out = dockerfile.render(_cfg(tmp_path))
    assert "FROM python:3.12-slim" in out
    assert "uv" in out
    assert "gosu" in out
    assert "APP_UID=1000" in out


def test_entrypoint_chowns_then_drops_to_appuser(tmp_path: Path) -> None:
    out = dockerfile.render_entrypoint(_cfg(tmp_path))
    assert "chown -R" in out
    assert 'exec gosu' in out
    assert "/app/.venv" in out
    assert "/app/.opencode/data" in out


# ---- docker-compose ------------------------------------------------------


def test_compose_minimal_web_has_fastapi_and_opencode_web(tmp_path: Path) -> None:
    out = compose.render(_cfg(tmp_path, project_name="proj", template="web"))
    assert "fastapi:" in out
    assert "opencode-web:" in out
    assert "network_mode: host" in out
    assert "proj_venv:" in out


def test_compose_full_template_includes_telegram_and_db(tmp_path: Path) -> None:
    out = compose.render(_cfg(tmp_path, project_name="proj", template="full"))
    assert "db:" in out
    assert "pgvector/pgvector" in out
    assert "telegram-bot:" in out


def test_compose_with_redis_and_qdrant(tmp_path: Path) -> None:
    out = compose.render(_cfg(
        tmp_path, project_name="proj",
        with_redis=True, with_qdrant=True,
    ))
    assert "redis:" in out
    assert "qdrant:" in out
    assert "proj_qdrant_data:" in out


def test_compose_with_cron_includes_cron_service(tmp_path: Path) -> None:
    out = compose.render(_cfg(
        tmp_path, project_name="proj", with_cron=True,
        cron_events_path=Path("ops/events.json"),
    ))
    assert "cron:" in out
    assert "CRON_EVENTS: /app/ops/events.json" in out


def test_compose_with_observability_langfuse(tmp_path: Path) -> None:
    out = compose.render(_cfg(
        tmp_path, project_name="proj", observability="langfuse",
    ))
    assert "langfuse:" in out


# ---- app/main + run.py ---------------------------------------------------


def test_app_main_exposes_health_and_list_agents(tmp_path: Path) -> None:
    out = app_files.render_app_main(_cfg(tmp_path, project_name="demo"))
    assert "/health" in out
    assert "/agents" in out
    # Project name appears in the FastAPI title.
    assert "title='demo'" in out


def test_app_main_exposes_run_and_fire_routes(tmp_path: Path) -> None:
    out = app_files.render_app_main(_cfg(tmp_path, project_name="demo"))
    assert "/agents/{name:path}/run" in out
    assert "/events/{event_id}/fire" in out
    assert "/runs/{run_id}" in out


def test_agent_runner_spawns_opencode_subprocess(tmp_path: Path) -> None:
    out = app_files.render_agent_runner(_cfg(tmp_path))
    assert "asyncio.create_subprocess_exec" in out
    assert "opencode" in out
    assert "XDG_DATA_HOME" in out
    assert "RUNS" in out  # in-memory state cache


def test_models_carry_cron_event_and_run_result(tmp_path: Path) -> None:
    out = app_files.render_models(_cfg(tmp_path))
    assert "class CronEvent" in out
    assert "class AgentRunRequest" in out
    assert "class AgentRunResult" in out
    assert "schedule" in out  # CronEvent field


def test_run_py_reads_host_port_from_env(tmp_path: Path) -> None:
    out = app_files.render_run_py(_cfg(tmp_path))
    assert "uvicorn.run" in out
    assert "'HOST'" in out
    assert "'PORT'" in out


# ---- cron driver + events.json -----------------------------------------


def test_events_json_is_valid_with_disabled_examples(tmp_path: Path) -> None:
    out = cron.render_events_json(_cfg(tmp_path, with_cron=True))
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert all("id" in e and "schedule" in e for e in parsed)
    # Examples ship disabled so no one accidentally triggers them.
    assert all(e.get("enabled") is False for e in parsed)


def test_cron_driver_supports_basic_cron_expression() -> None:
    """Spot-check the driver's _should_fire by exec'ing it (no install side effects)."""
    from datetime import datetime

    src_code = cron.render_driver(ScaffoldConfig(
        target=Path("/tmp/_unused"), project_name="demo",
    ))
    ns: dict = {}
    exec(src_code, ns)  # noqa: S102 - executing generator output in isolation
    should_fire = ns["_should_fire"]
    # '*/*/*/*/*' (5 stars) matches anything
    assert should_fire("* * * * *", datetime(2026, 5, 17, 12, 0))
    # Specific minute
    assert should_fire("0 * * * *", datetime(2026, 5, 17, 12, 0))
    assert not should_fire("0 * * * *", datetime(2026, 5, 17, 12, 30))
    # Malformed → False (driver tolerates without raising)
    assert not should_fire("bad", datetime(2026, 5, 17, 12, 0))


# ---- engine integration --------------------------------------------------


def test_engine_web_template_emits_dockerfile_and_compose(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "proj", project_name="proj", template="web")
    ScaffoldEngine(config=cfg).render()
    base = tmp_path / "proj"
    assert (base / "docker" / "Dockerfile").exists()
    assert (base / "docker" / "docker-entrypoint.sh").exists()
    assert (base / "docker" / "docker-compose.yml").exists()
    assert (base / "app" / "main.py").exists()
    assert (base / "app" / "models.py").exists()
    assert (base / "app" / "agent_runner.py").exists()
    assert (base / "run.py").exists()


def test_generated_app_modules_are_valid_python(tmp_path: Path) -> None:
    import ast
    cfg = _cfg(tmp_path / "proj", project_name="proj", template="web")
    ScaffoldEngine(config=cfg).render()
    base = tmp_path / "proj"
    ast.parse((base / "app" / "main.py").read_text())
    ast.parse((base / "app" / "models.py").read_text())
    ast.parse((base / "app" / "agent_runner.py").read_text())
    ast.parse((base / "run.py").read_text())


def test_cron_driver_posts_to_fastapi_not_direct_subprocess(tmp_path: Path) -> None:
    out = cron.render_driver(_cfg(tmp_path, with_cron=True))
    # Must POST to FASTAPI_URL/events/<id>/fire — not spawn opencode itself.
    assert "FASTAPI_URL" in out
    assert "/events/" in out and "/fire" in out
    assert "POST" in out
    assert "subprocess" not in out  # crucially: no direct agent invocation


def test_generated_cron_driver_parses(tmp_path: Path) -> None:
    import ast
    ast.parse(cron.render_driver(_cfg(tmp_path, with_cron=True)))


def test_engine_with_cron_writes_events_and_driver(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path / "proj", project_name="proj",
        template="web", with_cron=True,
        cron_events_path=Path("ops/events.json"),
    )
    ScaffoldEngine(config=cfg).render()
    base = tmp_path / "proj"
    assert (base / "ops" / "events.json").exists()
    assert (base / "cron" / "driver.py").exists()


def test_engine_barebones_skips_docker_files(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "proj", project_name="proj", template="barebones")
    ScaffoldEngine(config=cfg).render()
    base = tmp_path / "proj"
    assert not (base / "docker").exists()
    assert not (base / "app").exists()
