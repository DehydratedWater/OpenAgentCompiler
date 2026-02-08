"""OpenCodeServerManager — HTTP backend for OpenCode server."""

from __future__ import annotations

from typing import Any

from open_agent_compiler.managers._base import Manager


class OpenCodeServerManager(Manager):
    """Manage agent lifecycle via an OpenCode HTTP server."""

    def __init__(self, base_url: str = "http://localhost:8080") -> None:
        self._base_url = base_url
        self._deployed: dict[str, Any] | None = None

    async def deploy(self, compiled: dict[str, Any]) -> None:
        self._deployed = compiled

    async def invoke(self, payload: dict[str, Any]) -> Any:
        if self._deployed is None:
            raise RuntimeError("No agent deployed — call deploy() first")
        # TODO: POST to self._base_url with self._deployed config + payload
        return {"status": "stub", "payload": payload}

    async def teardown(self) -> None:
        self._deployed = None

    async def health_check(self) -> bool:
        return self._deployed is not None
