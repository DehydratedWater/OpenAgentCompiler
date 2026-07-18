"""Public API contract — every name in `open_agent_compiler.__all__` must resolve."""

from __future__ import annotations

import open_agent_compiler


def test_all_exports_are_present() -> None:
    missing = [
        name
        for name in open_agent_compiler.__all__
        if not hasattr(open_agent_compiler, name)
    ]
    assert not missing, f"missing exports: {missing}"


def test_version_is_pep440_string() -> None:
    assert isinstance(open_agent_compiler.__version__, str)
    parts = open_agent_compiler.__version__.split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts[:2])
