"""CompilationContext — contextvar-scoped per-pass facts."""

from __future__ import annotations

import threading

import pytest

from open_agent_compiler.model.core.compilation_context import (
    CompilationContext,
    active,
    current_context,
)


def test_current_context_outside_block_is_empty() -> None:
    ctx = current_context()
    assert ctx.variant_name is None
    assert ctx.feature_flags == {}
    assert ctx.flag("anything", default="fallback") == "fallback"


def test_active_block_pushes_and_pops() -> None:
    seen: CompilationContext | None = None
    with active(CompilationContext(variant_name="v1", feature_flags={"is_local": True})):
        seen = current_context()
        assert seen.variant_name == "v1"
        assert seen.flag("is_local") is True
    assert current_context().variant_name is None


def test_active_block_restores_previous_context_on_exception() -> None:
    outer = CompilationContext(variant_name="outer")
    with active(outer):
        with pytest.raises(RuntimeError):
            with active(CompilationContext(variant_name="inner")):
                assert current_context().variant_name == "inner"
                raise RuntimeError("boom")
        assert current_context().variant_name == "outer"
    assert current_context().variant_name is None


def test_nested_contexts() -> None:
    with active(CompilationContext(variant_name="a")):
        assert current_context().variant_name == "a"
        with active(CompilationContext(variant_name="b")):
            assert current_context().variant_name == "b"
        assert current_context().variant_name == "a"


def test_client_id_defaults_to_none_base_behavior() -> None:
    """Base single-tenant build: client_id is None, today's behavior."""
    assert current_context().client_id is None
    assert CompilationContext().client_id is None


def test_client_id_surfaced_on_current_context() -> None:
    with active(CompilationContext(client_id="acme", variant_name="v1")):
        ctx = current_context()
        assert ctx.client_id == "acme"
        assert ctx.variant_name == "v1"
    # Popped: back to base.
    assert current_context().client_id is None


def test_client_id_is_frozen() -> None:
    ctx = CompilationContext(client_id="acme")
    with pytest.raises(Exception):
        ctx.client_id = "other"  # type: ignore[misc]


def test_context_isolates_across_threads() -> None:
    """contextvars give each thread/asyncio task its own view by default."""
    results: dict[str, str | None] = {}

    def worker():
        results["t"] = current_context().variant_name

    with active(CompilationContext(variant_name="main")):
        t = threading.Thread(target=worker)
        t.start()
        t.join()

    assert results["t"] is None
