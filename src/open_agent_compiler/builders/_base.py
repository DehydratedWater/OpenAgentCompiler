"""Builder protocol — structural typing for all builders."""

from __future__ import annotations

from typing import Protocol, TypeVar

T = TypeVar("T")


class Builder(Protocol[T]):
    """Structural interface every builder satisfies."""

    def build(self) -> T: ...

    def reset(self) -> Builder[T]: ...
