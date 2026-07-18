"""TaskHandle — the contract for long-running agent / tool work.

Some tools and some agents don't complete in one call. Returning a
TaskHandle gives the caller a stable id + status that they can poll
(via the FastAPI scaffold's /runs/{run_id}/await endpoint or any
external dispatcher) without holding the original connection open.

Three resolution patterns the framework supports:

1. **Blocking** — caller waits for the result. Default for short
   tools (≤30s). Returns the typed Output directly.

2. **Fire-and-forget** — caller starts the work and walks away. The
   tool returns a TaskHandle with status='running'; the framework
   persists the run; the caller polls /runs/{run_id}/await later.

3. **Spawn-and-poll** — same as fire-and-forget but the spawned
   subprocess is a new opencode agent (Phase 21 pattern). The
   handle's `kind` field tells the caller which it was.

The model is intentionally minimal — the FastAPI runs router is
authoritative for status; this carries just enough state for a
caller (a tool, another agent, a cron driver) to know what to do
next.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal[
    "pending",   # accepted, not yet running
    "running",   # in progress
    "success",   # completed without error
    "failure",   # completed with error
    "timeout",   # exceeded await deadline (the await ended, the task may still be running)
]

TaskKind = Literal[
    "agent_run",        # an agent invocation (POST /agents/{name}/run)
    "spawned_agent",    # a SpawnAgentTool started a new agent
    "long_running_tool",  # a ScriptTool returned a handle instead of an output
]


class TaskHandle(BaseModel):
    """Stable reference to an in-progress or completed unit of work.

    A tool that can take more than ~30s to finish should return a
    TaskHandle from `execute()` instead of blocking. The framework's
    runtime detects the return type and registers the handle in the
    runs table so the caller can poll /runs/{run_id}/await.

    Fields:
      - run_id: stable id, matches `runs.run_id` when DB-backed.
      - kind:   what produced this handle.
      - status: latest known status — the caller refreshes via poll.
      - poll_url: optional fully-qualified poll URL when emitted by
        a FastAPI route; tools running outside the HTTP layer leave
        this None.
      - result: present only when status in ('success', 'failure').
      - error_message: present only when status == 'failure'.
      - eta_seconds: optional hint at expected duration so the caller
        can pick a sensible initial poll interval.
    """

    model_config = ConfigDict(frozen=False)

    run_id: str = Field(description="Stable identifier; key into the runs table.")
    kind: TaskKind = "agent_run"
    status: TaskStatus = "pending"
    poll_url: str | None = Field(
        default=None,
        description="Fully-qualified URL the caller can GET to refresh status.",
    )
    result: dict[str, Any] | None = Field(
        default=None,
        description="Populated when status in ('success', 'failure').",
    )
    error_message: str | None = None
    eta_seconds: float | None = Field(
        default=None,
        description="Hint for the caller's initial poll interval.",
    )

    @property
    def is_terminal(self) -> bool:
        """True when the task has reached a final state."""
        return self.status in ("success", "failure")

    def with_status(self, status: TaskStatus, **kw: Any) -> "TaskHandle":
        """Return a new TaskHandle with `status` and any other fields updated."""
        return self.model_copy(update={"status": status, **kw})
