"""The personalization package must contain NO raw provider endpoints.

Elicitation + judging route through the opencode teacher (OpencodeMutatorClient),
never a raw provider API. Enforce that structurally over the whole package.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.testing import assert_no_raw_provider_endpoints

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "open_agent_compiler" / "personalization"


def test_no_raw_provider_endpoints_in_personalization() -> None:
    assert_no_raw_provider_endpoints(PACKAGE_ROOT)
