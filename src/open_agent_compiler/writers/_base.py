"""Writer protocol — structural typing for all writers."""

from __future__ import annotations

from typing import Any, Protocol


class Writer(Protocol):
    """Structural interface every writer satisfies."""

    def write(self, compiled: dict[str, Any]) -> None: ...
