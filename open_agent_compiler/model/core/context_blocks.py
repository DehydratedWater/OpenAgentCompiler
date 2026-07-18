"""Composable prompt assembly with volatility-aware ordering.

Pattern mirrors the "prepended context" / "volatile context" shape
used by a production chat-assistant deployment: an agent's prompt is built from named
blocks, each marked with how often its content changes. The
PromptAssembler sorts blocks from most-stable to most-volatile so
the resulting prompt structure is easy to scan AND happens to be
optimal for provider-side prefill caching (the cacheable prefix is
just everything up to the first volatile block).

The volatility marking is about *prompt structure*. Cache friendliness
is a side effect — you get it for free when you write a well-structured
prompt with immutable persona/rules first and per-turn data last.

Users can override the auto-sort per-block via `position`.

Usage:

    persona = ContextBlock(
        name="persona", volatility="immutable",
        content="You are a thorough research assistant…",
    )
    rules = ContextBlock(
        name="security-rules", volatility="stable",
        content="Never write outside the workspace dir. …",
    )
    user_profile = ContextBlock(
        name="user-profile", volatility="fluid",
        content=lambda ctx: f"User: {ctx['name']}, tz={ctx['tz']}",
    )
    live_obs = ContextBlock(
        name="live-observations", volatility="volatile",
        content=lambda ctx: ctx["observations"],
    )
    assembler = PromptAssembler(blocks=[
        persona, rules, user_profile, live_obs,
    ])
    prompt = assembler.compose(input_context={
        "name": "Alice", "tz": "UTC+1",
        "observations": "<timestamped live data>",
    })
"""

from __future__ import annotations

from typing import Any, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Volatility tiers ordered from most-stable to most-volatile.
# Numeric ranks drive the auto-sort: lower rank → earlier in the prompt
# → more of the prefill cacheable on the provider side.
Volatility = Literal["immutable", "stable", "fluid", "volatile"]

_RANK: dict[str, int] = {
    "immutable": 0,
    "stable": 1,
    "fluid": 2,
    "volatile": 3,
}


def volatility_rank(v: Volatility) -> int:
    """Return the numeric sort rank for a volatility tier.

    Exposed so user code can write its own sorts without re-importing
    the private constant.
    """
    return _RANK[v]


# A block's content is either a static string or a builder that takes
# the per-invocation input_context dict and returns a string.
ContentBuilder = Callable[[dict[str, Any]], str]
ContentValue = Union[str, ContentBuilder]


class ContextBlock(BaseModel):
    """One named, volatility-tagged piece of a composed prompt.

    The content is either a literal string (cheap, evaluated at
    compose time identically every call) or a callable that receives
    the runtime `input_context` dict and returns the rendered string.
    Callable content is how per-session data (user profile, recent
    observations, chat history) plugs in.

    `position` is an explicit ordering override. By default blocks
    auto-sort by volatility rank (most-stable first). Set `position`
    to pin a block to a specific slot regardless of its volatility —
    use sparingly; the auto-sort produces the cache-friendliest
    structure when left alone.

    `cache_breakpoint=True` marks the END of a block that the user
    wants to be the last cacheable position. Tooling that emits
    Anthropic-style `cache_control: ephemeral` markers on the
    compiled prompt reads this flag.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    name: str = Field(description="Unique identifier within an assembly.")
    volatility: Volatility = Field(
        description=(
            "How often this block's content changes between invocations."
            " Auto-sort orders blocks by this rank ascending (immutable"
            " first → volatile last) for prompt-structure clarity and"
            " prefill-cache friendliness."
        ),
    )
    content: ContentValue = Field(
        description=(
            "Static string OR a callable taking input_context dict →"
            " rendered string. Callables let per-session data plug in"
            " without rebuilding the assembler each call."
        ),
    )
    position: int | None = Field(
        default=None,
        description=(
            "Explicit position override (smaller = earlier). When set,"
            " supersedes the auto-sort for this block. Two blocks with"
            " the same position fall back to volatility rank."
        ),
    )
    cache_breakpoint: bool = Field(
        default=False,
        description=(
            "Mark this block's end as the final cacheable position."
            " Compiled output emits a cache_control marker after it"
            " (provider-specific; Anthropic uses ephemeral)."
        ),
    )
    description: str | None = Field(
        default=None,
        description="Human-readable note about what this block carries.",
    )

    def render(self, input_context: dict[str, Any] | None = None) -> str:
        ctx = input_context or {}
        if callable(self.content):
            return self.content(ctx)
        return self.content

    def sort_key(self) -> tuple[int, int]:
        """Effective sort key: position override > volatility rank.

        When position is None, only the second element matters; sort
        is stable so registration order breaks volatility ties.
        """
        return (
            self.position if self.position is not None else 1_000_000,
            _RANK[self.volatility],
        )


class PromptAssembler(BaseModel):
    """A named, ordered set of ContextBlocks that composes to one prompt.

    The assembler is the unit users register against an agent. At
    compose-time it sorts the blocks (position overrides win, ties
    broken by volatility rank, ties broken by registration order)
    and joins them with `separator`.

    `cacheable_prefix(input_context)` returns the prefix up to and
    including the last block at or before the highest cache_breakpoint
    or before the first 'volatile' tier — whichever comes first. Use
    this to drive Anthropic / OpenAI prefill-cache markers on the
    compiled output.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    blocks: list[ContextBlock] = Field(default_factory=list)
    separator: str = Field(
        default="\n\n",
        description="String joining adjacent rendered blocks.",
    )
    name: str = Field(
        default="default",
        description="Identifier for this assembly (debug / observability).",
    )

    @model_validator(mode="after")
    def _unique_block_names(self) -> "PromptAssembler":
        names = [b.name for b in self.blocks]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(
                f"PromptAssembler {self.name!r} has duplicate block names: {dupes}"
            )
        return self

    def sorted_blocks(self) -> list[ContextBlock]:
        """Return blocks in their effective compose order.

        Stable sort: equal keys preserve registration order, so users
        can group blocks of the same volatility tier deliberately
        (e.g. two 'stable' tool-docs blocks stay in the order they
        were declared).
        """
        return sorted(self.blocks, key=ContextBlock.sort_key)

    def compose(
        self, input_context: dict[str, Any] | None = None,
    ) -> str:
        """Render every block and join with `separator`."""
        return self.separator.join(
            block.render(input_context) for block in self.sorted_blocks()
        )

    def cacheable_prefix(
        self, input_context: dict[str, Any] | None = None,
    ) -> str:
        """Return the prefix that's safe to mark cacheable.

        Walks the sorted blocks; includes a block in the prefix when:
          - It is at or below the 'fluid' tier (not 'volatile'), AND
          - We haven't already passed the user's explicit
            cache_breakpoint marker.

        Stops as soon as either condition fails. The point: callers
        that emit provider-specific cache markers on the compiled
        output can call this once at compile time and use its length
        as the boundary.
        """
        out: list[str] = []
        breakpoint_passed = False
        for block in self.sorted_blocks():
            if breakpoint_passed:
                break
            if block.volatility == "volatile":
                break
            out.append(block.render(input_context))
            if block.cache_breakpoint:
                breakpoint_passed = True
        return self.separator.join(out)

    def with_block(self, block: ContextBlock) -> "PromptAssembler":
        """Return a new assembler with `block` appended (immutable update)."""
        return self.model_copy(update={"blocks": [*self.blocks, block]})
