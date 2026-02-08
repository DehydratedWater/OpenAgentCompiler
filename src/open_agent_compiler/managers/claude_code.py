"""ClaudeCodeManager — subprocess backend for Claude Code CLI."""

from __future__ import annotations

from typing import Any

from open_agent_compiler.managers._base import Manager


class ClaudeCodeManager(Manager):
    """Manage agent lifecycle via the Claude Code CLI subprocess."""

    def __init__(self) -> None:
        self._deployed: dict[str, Any] | None = None

    async def deploy(self, compiled: dict[str, Any]) -> None:
        self._deployed = compiled

    async def invoke(self, payload: dict[str, Any]) -> Any:
        if self._deployed is None:
            raise RuntimeError("No agent deployed — call deploy() first")
        # TODO: launch claude-code subprocess with self._deployed config
        return {"status": "stub", "payload": payload}

    async def teardown(self) -> None:
        self._deployed = None

    async def health_check(self) -> bool:
        return self._deployed is not None
