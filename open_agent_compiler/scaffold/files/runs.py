"""`app/runs.py` + `app/persistence.py` generators.

Emitted alongside the FastAPI service when `with_postgres` is on.
Plugs run tracking into the existing /agents/{name}/run flow so
every invocation persists a row in the `runs` table and (per tool
call captured by the runner) into `tool_calls`.

Exposes a small read API for operators + the improvement loop:
  GET  /runs                       — list with optional ?agent= filter
  GET  /runs/{run_id}/detail       — run + its tool_calls
  GET  /metrics/tool-failures      — per-tool failure rates
"""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render_persistence_module(config: ScaffoldConfig) -> str:
    return '''"""Persist agent runs + tool calls via db.repositories.

`record_run` wraps run_agent so the result lands in the `runs` table
exactly once, regardless of which path called it (HTTP, cron, manual).
The repository functions accept an AsyncSession; this module owns the
short-lived session that brackets a single run.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

from app.models import AgentRunRequest, AgentRunResult
from db import repositories
from db.session import session_scope


RunFn = Callable[[str, AgentRunRequest], Awaitable[AgentRunResult]]


async def record_run(
    agent: str, req: AgentRunRequest, run_fn: RunFn,
) -> AgentRunResult:
    """Wrap a run_agent call with begin/complete persistence.

    The function:
      1. INSERT runs(...) with status='pending'.
      2. UPDATE → 'running' before delegating to run_fn.
      3. UPDATE → 'success' | 'failure' with the captured payload
         and duration_ms after run_fn returns / raises.

    On any exception, the run is marked 'failure' with the message
    and the exception is re-raised so FastAPI's error handler
    reports it. Failures stay queryable in /runs.
    """
    started_ms = int(time.time() * 1000)
    async with session_scope() as session:
        run_id = await repositories.create_run(
            session,
            agent_name=agent,
            request_payload=req.model_dump(),
        )
    # If the caller supplied a run_id, use that instead so external
    # systems can correlate by their own identifier.
    if req.run_id:
        run_id = req.run_id
    else:
        # Carry the DB-allocated id through to run_fn so the result
        # carries the same identifier.
        req = req.model_copy(update={"run_id": run_id})
    async with session_scope() as session:
        await repositories.mark_run_running(session, run_id)
    try:
        result = await run_fn(agent, req)
    except Exception as exc:  # noqa: BLE001
        duration_ms = int(time.time() * 1000) - started_ms
        async with session_scope() as session:
            await repositories.complete_run(
                session, run_id, status="failure",
                error_message=str(exc),
                duration_ms=duration_ms,
            )
        raise
    duration_ms = int(time.time() * 1000) - started_ms
    status = "success" if result.status == "completed" else "failure"
    async with session_scope() as session:
        await repositories.complete_run(
            session, run_id, status=status,
            result_payload=result.model_dump(),
            error_message=result.error,
            duration_ms=duration_ms,
        )
    return result
'''


def render_runs_router(config: ScaffoldConfig) -> str:
    return '''"""Read-side API for the runs + tool_calls tables.

These routes back operator dashboards and the improvement loop's
tool_failure_rate criterion (oac improve reads /metrics/tool-failures
to populate the metrics dict).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from db import repositories
from db.session import session_scope

router = APIRouter()


_TERMINAL_STATUSES = {"success", "failure"}


@router.get("/runs")
async def list_runs(
    agent: str | None = Query(default=None,
                              description="Filter to one agent's runs."),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    async with session_scope() as session:
        return await repositories.list_runs(
            session, agent_name=agent, limit=limit,
        )


@router.get("/runs/{run_id}/detail")
async def run_detail(run_id: str) -> dict[str, Any]:
    async with session_scope() as session:
        detail = await repositories.get_run_detail(session, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    return detail


@router.get("/runs/{run_id}/await")
async def run_await(
    run_id: str,
    timeout_s: float = Query(
        default=30.0, ge=0.5, le=600.0,
        description="Max time to wait for a terminal status before returning.",
    ),
    poll_interval_s: float = Query(
        default=1.0, ge=0.1, le=10.0,
        description="How often to re-check the runs table.",
    ),
) -> dict[str, Any]:
    """Long-poll until the run reaches a terminal status or timeout.

    Callers that want a blocking API call instead of polling the
    plain /runs/{run_id}/detail endpoint themselves use this:

        GET /runs/run_abc123/await?timeout_s=60

    Returns the same payload as /runs/{run_id}/detail, plus a top-level
    `awaited` boolean: True when the call returned because the run
    reached a terminal state; False when the timeout fired (the run
    may still be running — re-call to keep waiting).

    The underlying task is NOT cancelled when the await times out —
    this endpoint is read-only.
    """
    elapsed = 0.0
    last_detail: dict[str, Any] | None = None
    while elapsed < timeout_s:
        async with session_scope() as session:
            last_detail = await repositories.get_run_detail(session, run_id)
        if last_detail is None:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        if last_detail.get("status") in _TERMINAL_STATUSES:
            return {**last_detail, "awaited": True}
        await asyncio.sleep(poll_interval_s)
        elapsed += poll_interval_s
    return {**(last_detail or {"run_id": run_id}), "awaited": False}


@router.get("/metrics/tool-failures")
async def metrics_tool_failures(
    agent: str | None = Query(default=None),
    since: str | None = Query(
        default=None,
        description="ISO-8601 lower bound on tool_calls.invoked_at.",
    ),
) -> list[dict[str, Any]]:
    """Per-tool failure rate. Lower-is-better metric.

    The improvement loop's `tool_failure_rate` criterion reads this
    endpoint when run with `--metrics-url <fastapi>/metrics/...` so
    candidates can be scored against actual production failure data
    (not just synthetic test artifacts).
    """
    async with session_scope() as session:
        return await repositories.tool_failure_rate(
            session, agent_name=agent, since_iso=since,
        )


@router.get("/metrics/context-volatility")
async def metrics_context_volatility(
    agent: str | None = Query(default=None),
    since: str | None = Query(
        default=None,
        description="ISO-8601 lower bound on observed_at.",
    ),
) -> list[dict[str, Any]]:
    """Declared vs observed volatility per context block.

    Long-running systems use this to detect mis-tagged blocks:
      - A block declared 'stable' with change_rate ~= 1.0 actually
        belongs in 'fluid' or 'volatile' — the current tagging
        breaks the assembler's auto-sort and hurts prompt structure.
      - A block declared 'volatile' with change_rate << 1.0 is
        wasting cache budget — retag it 'fluid' or 'stable' to keep
        more of the prompt prefix cache-eligible.

    Output rows: block_name, declared, total_runs, distinct_hashes,
    change_rate. Same data shape as /metrics/tool-failures so
    operator dashboards can use one chart pattern for both.
    """
    async with session_scope() as session:
        return await repositories.context_volatility_actual(
            session, agent_name=agent, since_iso=since,
        )
'''
