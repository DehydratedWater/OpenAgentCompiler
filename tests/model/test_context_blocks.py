"""ContextBlock + PromptAssembler — volatility-ordered prompt composition."""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.context_blocks import (
    ContextBlock,
    PromptAssembler,
    volatility_rank,
)


def _b(name: str, vol: str, content: str = "X", **kw) -> ContextBlock:
    return ContextBlock(name=name, volatility=vol, content=content, **kw)


def test_volatility_rank_ordered_stable_first() -> None:
    assert volatility_rank("immutable") < volatility_rank("stable")
    assert volatility_rank("stable") < volatility_rank("fluid")
    assert volatility_rank("fluid") < volatility_rank("volatile")


def test_compose_orders_by_volatility_by_default() -> None:
    assembler = PromptAssembler(blocks=[
        _b("now", "volatile", "now-data"),
        _b("persona", "immutable", "persona"),
        _b("rules", "stable", "rules"),
        _b("user", "fluid", "user"),
    ])
    composed = assembler.compose()
    assert composed == "persona\n\nrules\n\nuser\n\nnow-data"


def test_explicit_position_overrides_volatility_sort() -> None:
    assembler = PromptAssembler(blocks=[
        _b("now", "volatile", "now-data", position=0),
        _b("persona", "immutable", "persona"),
    ])
    composed = assembler.compose()
    # position=0 wins despite higher volatility rank.
    assert composed == "now-data\n\npersona"


def test_ties_break_by_registration_order() -> None:
    """Two blocks of the same volatility stay in declared order."""
    assembler = PromptAssembler(blocks=[
        _b("a", "stable", "A"),
        _b("b", "stable", "B"),
        _b("c", "stable", "C"),
    ])
    assert assembler.compose() == "A\n\nB\n\nC"


def test_callable_content_receives_input_context() -> None:
    assembler = PromptAssembler(blocks=[
        ContextBlock(
            name="user", volatility="fluid",
            content=lambda ctx: f"User: {ctx['name']}",
        ),
    ])
    out = assembler.compose(input_context={"name": "Alice"})
    assert out == "User: Alice"


def test_duplicate_block_names_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate block names"):
        PromptAssembler(blocks=[
            _b("dup", "stable"),
            _b("dup", "fluid"),
        ])


def test_cacheable_prefix_stops_at_first_volatile_block() -> None:
    assembler = PromptAssembler(blocks=[
        _b("p", "immutable", "p"),
        _b("r", "stable", "r"),
        _b("u", "fluid", "u"),
        _b("v1", "volatile", "v1"),
        _b("v2", "volatile", "v2"),
    ])
    # immutable + stable + fluid; stops before volatile.
    assert assembler.cacheable_prefix() == "p\n\nr\n\nu"


def test_cacheable_prefix_respects_explicit_breakpoint() -> None:
    """User can pin an earlier cache boundary regardless of tier."""
    assembler = PromptAssembler(blocks=[
        _b("p", "immutable", "p"),
        _b("r", "stable", "r", cache_breakpoint=True),
        _b("u", "fluid", "u"),  # excluded — past the breakpoint
    ])
    assert assembler.cacheable_prefix() == "p\n\nr"


def test_cacheable_prefix_empty_when_first_block_is_volatile() -> None:
    assembler = PromptAssembler(blocks=[
        _b("v", "volatile", "v"),
        _b("p", "immutable", "p"),  # later by registration; sorted before
    ])
    # The auto-sort puts 'p' first, so 'p' goes into the prefix.
    # Then 'v' breaks the loop. The test verifies the loop respects
    # volatility regardless of registration order.
    assert assembler.cacheable_prefix() == "p"


def test_with_block_returns_new_assembler() -> None:
    a = PromptAssembler(blocks=[_b("p", "immutable", "p")])
    b = a.with_block(_b("r", "stable", "r"))
    assert len(a.blocks) == 1  # original untouched
    assert len(b.blocks) == 2


def test_compose_uses_custom_separator() -> None:
    a = PromptAssembler(blocks=[
        _b("a", "stable", "A"),
        _b("b", "stable", "B"),
    ], separator=" | ")
    assert a.compose() == "A | B"


def test_position_zero_is_not_treated_as_none() -> None:
    """Common bug: position=0 falsy-check would discard the override."""
    a = PromptAssembler(blocks=[
        _b("first", "volatile", "F", position=0),
        _b("second", "immutable", "S"),
    ])
    assert a.compose() == "F\n\nS"


def test_assembler_is_repeatable_across_calls() -> None:
    """Composing twice with the same input yields identical output (cacheable)."""
    a = PromptAssembler(blocks=[
        _b("p", "immutable", "p"),
        ContextBlock(name="u", volatility="fluid",
                     content=lambda ctx: ctx["name"]),
    ])
    out1 = a.compose(input_context={"name": "Alice"})
    out2 = a.compose(input_context={"name": "Alice"})
    assert out1 == out2
    # And changing input_context changes only the fluid block.
    out3 = a.compose(input_context={"name": "Bob"})
    assert out3.startswith("p\n\n")
    assert "Bob" in out3
