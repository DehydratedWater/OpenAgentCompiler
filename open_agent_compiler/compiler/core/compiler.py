"""Base Compiler protocol shared by all dialects (opencode, claude, pi, …).

Each dialect implements its own concrete subclass that takes the resolved
agent variants plus a target path and produces the dialect's artifacts.

Dialects register themselves in open_agent_compiler.compiler.dialects.registry; the
public API resolves a target string ("opencode" / "claude" / "pi") to
the matching Dialect via that registry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from open_agent_compiler.model.core.agent_model import AgentVariant


class Compiler(ABC):
    """Base contract for every dialect.

    Subclasses must:
    - set `dialect_name` (registered with the registry)
    - implement compile()

    `supports_features` is a free-form set of capability flags consumers
    can introspect — useful for the future Phase 8 dialect-comparison
    work without forcing rigid interface bumps.
    """

    dialect_name: ClassVar[str] = ""
    supports_features: ClassVar[frozenset[str]] = frozenset()

    def __init__(
        self,
        target: Path,
        resolved_variants: dict[str, AgentVariant],
        options: dict | None = None,
    ) -> None:
        self.target = target
        self.resolved_variants = resolved_variants
        # Free-form compile options (e.g. {"native_tools": True}) flowed
        # from CompileScript; dialects read what they understand.
        self.options = options or {}

    @abstractmethod
    def compile(self) -> None: ...
