"""CompilationContext — scoped per-pass facts for agent factories.

Agent factories sometimes need to know about the current compile pass
(is this the local-only build? is vision available? which access
profile is bound? which mock set is active?) before they can decide
what skills / tools to include.

Pre-framework deployments did this with module-level globals plus
`is_compiling_local()` / `is_compiling_vision()` functions. Globals
are racy (they leak across tests, persist across passes if not reset)
and untyped (no static guarantees about which flags exist).

CompilationContext is a frozen Pydantic model surfaced via a
contextvars.ContextVar. The compiler pushes the context for the
duration of one variant's compile pass; factories read it inside that
window:

    from open_agent_compiler.model.core.compilation_context import current_context

    def my_agent_factory():
        ctx = current_context()
        if ctx.flag("is_local"):
            tools = [local_only_tool(), shared_tool()]
        else:
            tools = [shared_tool()]
        return AgentBuilder().tools(tools).build()

Outside an active pass, current_context() returns a fresh empty
context — so factories called from tests or REPLs never break.
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field


class CompilationContext(BaseModel):
    """Per-pass facts available to factories during one compile.

    The context is intentionally narrow: variant identity + symbolic
    profile names + a free-form feature_flags dict. Concrete state
    (resolved bindings, mock dispatchers) lives elsewhere and is looked
    up by these names — keeping the context cheap to construct and
    serialize for test artifacts.
    """

    model_config = ConfigDict(frozen=True)

    variant_name: str | None = None
    variant_postfix: str = ""
    access_profile_name: str | None = None
    mock_profile_name: str | None = None
    client_id: str | None = Field(
        default=None,
        description=(
            "Tenant/client this compile pass is personalized for. None (the"
            " default) is the base, single-tenant build — today's behavior."
            " When set, per-client promotion buckets"
            " (.oac/promoted/<client_id>/) are consulted, mirroring how"
            " model_class selects per-class snapshot slots. Factories can"
            " read it to overlay client-specific tools/prompts at compile time."
        ),
    )
    feature_flags: dict[str, Any] = Field(default_factory=dict)

    def flag(self, name: str, default: Any = False) -> Any:
        return self.feature_flags.get(name, default)


# The ContextVar holds the current active context; outside any
# active() block we return EMPTY so callers never need to None-check.
_EMPTY = CompilationContext()
_active: contextvars.ContextVar[CompilationContext] = contextvars.ContextVar(
    "_oac_compilation_context", default=_EMPTY,
)


def current_context() -> CompilationContext:
    """Return the active context (or an empty default outside an active pass)."""
    return _active.get()


@contextlib.contextmanager
def active(ctx: CompilationContext) -> Iterator[CompilationContext]:
    """Push `ctx` for the lifetime of the with-block, restore on exit.

    Reentrant — nested calls work, and on exit the previous context is
    restored even if the body raises.
    """
    token = _active.set(ctx)
    try:
        yield ctx
    finally:
        _active.reset(token)
