"""Manager protocol — structural typing for all managers."""

from __future__ import annotations

from typing import Any, Protocol


class Manager(Protocol):
    """Structural interface every manager satisfies."""

    async def deploy(self, compiled: dict[str, Any]) -> None: ...

    async def invoke(self, payload: dict[str, Any]) -> Any: ...

    async def teardown(self) -> None: ...

    async def health_check(self) -> bool: ...
