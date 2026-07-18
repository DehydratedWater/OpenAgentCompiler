"""`app/dispatch.py` — mode-aware run dispatcher (Phase 23).

Branches the POST /agents/{name}/run flow based on request.mode:

  * sync             — block; return the result body inline (default).
  * async            — return a stub AgentRunResult with status='running'
                       and a poll_url right away; the actual run is
                       launched via asyncio.create_task so the response
                       returns immediately.
  * fire_and_forget  — same as async, but if `callback_url` is set the
                       server POSTs the final AgentRunResult there when
                       the run terminates. The caller is expected NOT
                       to poll.

All three paths share the same persistence layer (when postgres is
enabled): runs land in the `runs` table identically regardless of
calling mode.
"""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render_dispatch_module(config: ScaffoldConfig) -> str:
    return '''"""Mode-aware run dispatcher — sync vs async vs fire_and_forget."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.models import AgentRunRequest, AgentRunResult

log = logging.getLogger(__name__)

RunFn = Callable[[str, AgentRunRequest], Awaitable[AgentRunResult]]


async def dispatch_run(
    name: str, req: AgentRunRequest, run_fn: RunFn,
    *, with_persistence: bool = False,
) -> AgentRunResult:
    """Run the agent according to req.mode + req.retry policy.

    sync             → await execution; return result inline.
    async            → schedule; return a 'running' stub.
    fire_and_forget  → schedule + optional callback POST; return 'running'.

    When req.retry is set, each mode walks the RetryPolicy: first
    attempt unconditionally, subsequent attempts skip when their
    `when` condition doesn't match the previous outcome. Every
    attempt's outcome is appended to result.fallback_chain so the
    escalation path stays queryable via /runs/{run_id}/detail.
    """
    if with_persistence:
        # Local import keeps this module importable in the no-postgres
        # template (where app.persistence is not generated).
        from app.persistence import record_run
        wrapped: RunFn = lambda agent, r: record_run(agent, r, run_fn)
    else:
        wrapped = run_fn

    if req.mode == "sync":
        return await _execute_with_retry(wrapped, name, req)

    # Async + fire-and-forget share the stub-response path.
    run_id = req.run_id or f"bg_{uuid.uuid4().hex[:12]}"
    stub = AgentRunResult(
        run_id=run_id, agent=name, status="running",
        started_at=datetime.now().isoformat(timespec="seconds"),
    )
    if req.mode == "async":
        asyncio.create_task(_drain(wrapped, name, req, run_id))
    else:  # fire_and_forget
        asyncio.create_task(
            _drain_with_callback(wrapped, name, req, run_id, req.callback_url)
        )
    return stub


async def _execute_with_retry(
    run_fn: RunFn, name: str, req: AgentRunRequest,
) -> AgentRunResult:
    """Walk the RetryPolicy (if any), recording each attempt.

    Returns the FIRST successful AgentRunResult, or the LAST attempt
    if every step failed. The result\\'s fallback_chain lists every
    attempt with its variant, status, and error so operators can
    see the escalation path.
    """
    if req.retry is None or not req.retry.steps:
        return await run_fn(name, req)

    chain: list[dict] = []
    last_result: AgentRunResult | None = None
    last_status: str = "pending"
    for i, step in enumerate(req.retry.steps):
        if not _step_applies(step, i, last_status):
            chain.append({
                "variant": step.variant, "status": "skipped",
                "note": step.note or f"when={step.when} did not match",
            })
            continue
        attempt_req = req.model_copy(update={
            "variant": step.variant,
            "timeout_s": step.timeout_s,
            # Each attempt gets its own run_id derived from the
            # caller\\'s — keeps DB rows separable per escalation step.
            "run_id": (
                f"{req.run_id}_step{i}" if req.run_id
                else f"step{i}_{uuid.uuid4().hex[:8]}"
            ),
            # Clear the retry on the inner call so we don\\'t recurse.
            "retry": None,
        })
        try:
            attempt_result = await run_fn(name, attempt_req)
        except Exception as exc:  # noqa: BLE001
            log.exception("retry step %s failed", i)
            chain.append({
                "variant": step.variant, "status": "failed",
                "error": str(exc), "note": step.note,
            })
            last_status = "failed"
            continue
        chain.append({
            "variant": step.variant,
            "status": attempt_result.status,
            "return_code": attempt_result.return_code,
            "error": attempt_result.error,
            "note": step.note,
        })
        last_result = attempt_result
        last_status = attempt_result.status
        if attempt_result.status == "completed":
            attempt_result.fallback_chain = chain
            return attempt_result
    # Every step failed (or got skipped). Return the last actual
    # result if we have one; otherwise fabricate a failure.
    if last_result is not None:
        last_result.fallback_chain = chain
        return last_result
    return AgentRunResult(
        run_id=req.run_id or "no_attempt",
        agent=name, status="failed",
        error="all retry steps skipped — no attempt was made",
        fallback_chain=chain,
    )


def _step_applies(step, index: int, last_status: str) -> bool:
    """Decide whether to execute this step given the previous status.

    The first step always runs regardless of its `when` value, so
    a policy with one step behaves like a plain variant call.
    """
    if index == 0:
        return True
    if step.when == "always":
        return True
    if step.when == "on_failure":
        return last_status in ("failed", "timeout", "unreachable")
    if step.when == "on_timeout":
        return last_status == "timeout"
    return False


async def _drain(
    run_fn: RunFn, name: str, req: AgentRunRequest, run_id: str,
) -> None:
    """Run the agent; persistence + RUNS dict carry the final state."""
    try:
        await _execute_with_retry(
            run_fn, name, req.model_copy(update={"run_id": run_id}),
        )
    except Exception:  # noqa: BLE001
        # Persistence already records failures; just keep the loop alive.
        log.exception("background run %s failed", run_id)


async def _drain_with_callback(
    run_fn: RunFn, name: str, req: AgentRunRequest, run_id: str,
    callback_url: str | None,
) -> None:
    """Run the agent (with retries), then POST the final result.

    Uses urllib.request to avoid adding an httpx dependency on the
    scaffold. Callback failures are logged but never re-raised; the
    underlying run still completed and was persisted.
    """
    try:
        result = await _execute_with_retry(
            run_fn, name, req.model_copy(update={"run_id": run_id}),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("fire-and-forget run %s failed", run_id)
        result = AgentRunResult(
            run_id=run_id, agent=name, status="failed",
            error=str(exc),
        )
    if not callback_url:
        return
    try:
        payload = json.dumps(result.model_dump()).encode("utf-8")
        request = urllib.request.Request(
            callback_url, data=payload,
            headers={"content-type": "application/json"},
        )
        # The POST happens in a thread so we don't block the event loop
        # on a slow callback receiver.
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: urllib.request.urlopen(request, timeout=15)
        )
    except Exception:  # noqa: BLE001
        log.exception("callback POST to %s failed", callback_url)
'''
