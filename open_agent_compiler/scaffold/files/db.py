"""`db/session.py`, `migrations/` generators — postgres+pgvector path.

Emitted when `ScaffoldConfig.with_postgres` is True. Mirrors a
mature production deployment's pattern: async SQLAlchemy
engine + AsyncSession factory + Alembic env (async pattern) + a
seed migration creating the `runs` and `tool_calls` tables plus
the pgvector extension so the user can `oac improve` and `oac test`
out of the box without hand-wiring DDL.
"""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render_session_module(config: ScaffoldConfig) -> str:
    return f'''"""Async SQLAlchemy engine + AsyncSession factory for {config.project_name}.

Reads DATABASE_URL from the environment (defaults to the docker-compose
service hostname). Use:

    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        ...

The Alembic env reads the same URL via `get_database_url()`.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_URL = "postgresql+asyncpg://oac:oac@db:5432/{config.project_name}"


def get_database_url() -> str:
    """Resolve the database URL: env var > default compose hostname."""
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


engine = create_async_engine(get_database_url(), echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Convenience: `async with session_scope() as session: ...`."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
'''


def render_alembic_ini(config: ScaffoldConfig) -> str:
    return f'''# Alembic configuration for {config.project_name}.
# The actual URL is resolved at runtime via env.py / db.session.get_database_url.

[alembic]
script_location = migrations
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url = postgresql+asyncpg://oac:oac@db:5432/{config.project_name}

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
'''


def render_alembic_env(config: ScaffoldConfig) -> str:
    return '''"""Alembic environment — manual SQL migrations under an async engine.

Mirrors the production pattern (no autogenerate; the user controls
the SQL). The URL is resolved through db.session.get_database_url
so the same env var works for the app and for migrations.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import MetaData, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from db.session import get_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = MetaData()


def _url() -> str:
    return get_database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''


def render_alembic_script_template(config: ScaffoldConfig) -> str:
    """The Mako template Alembic uses for `alembic revision -m '...'`."""
    return '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""

from collections.abc import Sequence

from alembic import op

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''


def render_seed_migration(config: ScaffoldConfig) -> str:
    """Seed migration: pgvector extension + runs + tool_calls tables.

    These two tables back the run-tracking service (Phase 18). Even
    if the user adds more tables for their domain, the runs/tool_calls
    tables let oac improve and the failure-rate criterion work
    out-of-the-box without further DDL.
    """
    return '''"""Initial schema — pgvector + run-tracking tables.

Revision ID: 001_initial
"""

from collections.abc import Sequence

from alembic import op

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Vector embeddings extension — safe to call repeatedly thanks to
    # IF NOT EXISTS. Removes a class of "extension not found" failures
    # that bite when migrations are split across environments.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Run-tracking: every POST /agents/{name}/run lands here, with
    # tool_calls aggregating per-invocation activity for the
    # failure-rate criterion (see oac improve).
    op.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id BIGSERIAL PRIMARY KEY,
            run_id VARCHAR(80) UNIQUE NOT NULL,
            agent_name VARCHAR(200) NOT NULL,
            status VARCHAR(20) NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            request_payload JSONB DEFAULT '{}'::jsonb,
            result_payload JSONB DEFAULT '{}'::jsonb,
            error_message TEXT,
            duration_ms INTEGER,
            CHECK (status IN ('pending', 'running', 'success', 'failure'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_runs_agent_name ON runs(agent_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS tool_calls (
            id BIGSERIAL PRIMARY KEY,
            run_id VARCHAR(80) NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            tool_name VARCHAR(200) NOT NULL,
            invoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            input_payload JSONB DEFAULT '{}'::jsonb,
            output_payload JSONB DEFAULT '{}'::jsonb,
            error_message TEXT,
            succeeded BOOLEAN NOT NULL,
            duration_ms INTEGER
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id ON tool_calls(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name ON tool_calls(tool_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_succeeded ON tool_calls(succeeded)")

    # Phase 19: context-block volatility tracking. Each block's
    # rendered content is hashed at run time; comparing hashes
    # across runs surfaces how often a block actually changes vs
    # its declared volatility tier. Mismatches are signal: a block
    # declared 'stable' that changes every run should be retagged
    # 'fluid' or 'volatile' to keep the prompt structure honest.
    op.execute("""
        CREATE TABLE IF NOT EXISTS context_block_versions (
            id BIGSERIAL PRIMARY KEY,
            run_id VARCHAR(80) NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            block_name VARCHAR(200) NOT NULL,
            declared_volatility VARCHAR(20) NOT NULL,
            content_hash CHAR(64) NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (declared_volatility IN ('immutable', 'stable', 'fluid', 'volatile'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_cbv_run_id ON context_block_versions(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_cbv_block_name ON context_block_versions(block_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_cbv_hash ON context_block_versions(block_name, content_hash)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS context_block_versions")
    op.execute("DROP TABLE IF EXISTS tool_calls")
    op.execute("DROP TABLE IF EXISTS runs")
    # Leave the extension in place — other migrations may depend on it.
'''


def render_repositories(config: ScaffoldConfig) -> str:
    return '''"""Repository layer — DB access for runs + tool_calls.

Keeps SQL out of the route handlers and the agent runner. Each
function takes an AsyncSession and returns plain dicts (so the
FastAPI side doesn't have to import ORM models).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def create_run(
    session: AsyncSession, *,
    agent_name: str, request_payload: dict[str, Any],
) -> str:
    """Insert a fresh `runs` row in 'pending' status; return run_id."""
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    await session.execute(
        text("""
            INSERT INTO runs(run_id, agent_name, status, request_payload)
            VALUES (:run_id, :agent_name, 'pending', CAST(:payload AS jsonb))
        """),
        {
            "run_id": run_id, "agent_name": agent_name,
            "payload": json.dumps(request_payload),
        },
    )
    return run_id


async def mark_run_running(session: AsyncSession, run_id: str) -> None:
    await session.execute(
        text("UPDATE runs SET status='running' WHERE run_id=:run_id"),
        {"run_id": run_id},
    )


async def complete_run(
    session: AsyncSession, run_id: str, *,
    status: str, result_payload: dict[str, Any] | None = None,
    error_message: str | None = None, duration_ms: int | None = None,
) -> None:
    await session.execute(
        text("""
            UPDATE runs
               SET status=:status,
                   completed_at=:completed_at,
                   result_payload=CAST(:result AS jsonb),
                   error_message=:err,
                   duration_ms=:duration_ms
             WHERE run_id=:run_id
        """),
        {
            "run_id": run_id, "status": status,
            "completed_at": _now(),
            "result": json.dumps(result_payload or {}),
            "err": error_message,
            "duration_ms": duration_ms,
        },
    )


async def record_tool_call(
    session: AsyncSession, *,
    run_id: str, tool_name: str,
    input_payload: dict[str, Any] | None = None,
    output_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    succeeded: bool = True,
    duration_ms: int | None = None,
) -> None:
    await session.execute(
        text("""
            INSERT INTO tool_calls(
                run_id, tool_name, input_payload, output_payload,
                error_message, succeeded, duration_ms
            ) VALUES (
                :run_id, :tool_name, CAST(:inp AS jsonb), CAST(:out AS jsonb),
                :err, :succeeded, :duration_ms
            )
        """),
        {
            "run_id": run_id, "tool_name": tool_name,
            "inp": json.dumps(input_payload or {}),
            "out": json.dumps(output_payload or {}),
            "err": error_message,
            "succeeded": succeeded,
            "duration_ms": duration_ms,
        },
    )


async def list_runs(
    session: AsyncSession, *,
    agent_name: str | None = None, limit: int = 50,
) -> list[dict[str, Any]]:
    where = ""
    params: dict[str, Any] = {"lim": limit}
    if agent_name:
        where = "WHERE agent_name = :agent_name"
        params["agent_name"] = agent_name
    result = await session.execute(
        text(f"""
            SELECT run_id, agent_name, status, started_at,
                   completed_at, duration_ms, error_message
              FROM runs
              {where}
             ORDER BY started_at DESC
             LIMIT :lim
        """),
        params,
    )
    return [dict(row._mapping) for row in result]


async def get_run_detail(
    session: AsyncSession, run_id: str,
) -> dict[str, Any] | None:
    run_result = await session.execute(
        text("SELECT * FROM runs WHERE run_id = :run_id"),
        {"run_id": run_id},
    )
    row = run_result.first()
    if row is None:
        return None
    out = dict(row._mapping)
    calls_result = await session.execute(
        text("""
            SELECT tool_name, invoked_at, succeeded, duration_ms,
                   error_message
              FROM tool_calls
             WHERE run_id = :run_id
             ORDER BY invoked_at ASC
        """),
        {"run_id": run_id},
    )
    out["tool_calls"] = [dict(r._mapping) for r in calls_result]
    return out


async def record_context_blocks(
    session: AsyncSession, *,
    run_id: str, blocks: list[dict[str, Any]],
) -> None:
    """Persist per-block (name, declared_volatility, content_hash) snapshots.

    Expected block shape:
        {"name": str, "volatility": "immutable|stable|fluid|volatile",
         "content_hash": "<sha256 of rendered content>"}

    Call once per run after the prompt is assembled. Comparing hashes
    across runs powers the /metrics/context-volatility endpoint.
    """
    if not blocks:
        return
    values_rows = []
    params: dict[str, Any] = {"run_id": run_id}
    for i, block in enumerate(blocks):
        params[f"name_{i}"] = block["name"]
        params[f"vol_{i}"] = block["volatility"]
        params[f"hash_{i}"] = block["content_hash"]
        values_rows.append(f"(:run_id, :name_{i}, :vol_{i}, :hash_{i})")
    values_sql = ", ".join(values_rows)
    await session.execute(
        text(f"""
            INSERT INTO context_block_versions(
                run_id, block_name, declared_volatility, content_hash
            ) VALUES {values_sql}
        """),
        params,
    )


async def context_volatility_actual(
    session: AsyncSession, *,
    agent_name: str | None = None,
    since_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Per-block: declared volatility vs measured change rate.

    Returns one row per block_name with:
      - declared (last seen)
      - total_runs (observation count)
      - distinct_hashes (how many unique values seen)
      - change_rate = distinct_hashes / total_runs

    Compare declared volatility tier with change_rate to spot
    mismatches: a block declared 'stable' with change_rate ~= 1.0 is
    actually volatile; a block declared 'volatile' with change_rate
    << 1.0 is wasting cache budget.
    """
    where_parts = []
    params: dict[str, Any] = {}
    if agent_name:
        where_parts.append(
            "run_id IN (SELECT run_id FROM runs WHERE agent_name = :agent_name)"
        )
        params["agent_name"] = agent_name
    if since_iso:
        where_parts.append("observed_at >= :since")
        params["since"] = since_iso
    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    result = await session.execute(
        text(f"""
            SELECT block_name,
                   MAX(declared_volatility) AS declared,
                   COUNT(*) AS total_runs,
                   COUNT(DISTINCT content_hash) AS distinct_hashes,
                   (COUNT(DISTINCT content_hash)::float
                     / NULLIF(COUNT(*), 0)) AS change_rate
              FROM context_block_versions
              {where}
             GROUP BY block_name
             ORDER BY change_rate DESC NULLS LAST, block_name ASC
        """),
        params,
    )
    return [dict(row._mapping) for row in result]


async def tool_failure_rate(
    session: AsyncSession, *,
    agent_name: str | None = None, since_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Per-tool failure rate. Used by the `tool_failure_rate` criterion."""
    where_parts = []
    params: dict[str, Any] = {}
    if agent_name:
        where_parts.append(
            "tc.run_id IN (SELECT run_id FROM runs WHERE agent_name = :agent_name)"
        )
        params["agent_name"] = agent_name
    if since_iso:
        where_parts.append("tc.invoked_at >= :since")
        params["since"] = since_iso
    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    result = await session.execute(
        text(f"""
            SELECT tool_name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN succeeded THEN 0 ELSE 1 END) AS failures,
                   (SUM(CASE WHEN succeeded THEN 0 ELSE 1 END)::float
                     / NULLIF(COUNT(*), 0)) AS failure_rate
              FROM tool_calls tc
              {where}
             GROUP BY tool_name
             ORDER BY failure_rate DESC NULLS LAST, tool_name ASC
        """),
        params,
    )
    return [dict(row._mapping) for row in result]
'''
