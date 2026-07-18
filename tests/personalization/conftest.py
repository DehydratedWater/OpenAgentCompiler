"""Shared mocks for Phase D personalization tests.

A fake teacher exposing `.complete(system, user, model=...)` that returns a canned
string — the single IO seam, never a live opencode/qwen/z.ai/network call. Plus a
ready-made valid ClientSpec for the probe/judge tests.
"""

from __future__ import annotations

import json

import pytest

from open_agent_compiler.personalization.spec import ClientSpec, ExampleTask


class FakeTeacher:
    """Canned `.complete` stub, recording the calls it received.

    Construct with a fixed `response` string (what the teacher 'returns'). The
    recorded `(system, user, model)` tuples are kept on `.calls` for assertions.
    """

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str, str | None]] = []

    def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        self.calls.append((system, user, model))
        return self.response

    @classmethod
    def returning_spec_json(cls, payload: dict) -> "FakeTeacher":
        return cls(json.dumps(payload))


VALID_SPEC_PAYLOAD = {
    "goal": "Triage inbound support emails and draft replies",
    "preferences": ["Friendly but concise tone", "Prefer bullet points"],
    "constraints": ["Never promise a refund", "Never share internal pricing"],
    "example_tasks": [
        {
            "prompt": "Customer says their order #1234 never arrived. Draft a reply.",
            "expected_outcome": "Apologetic reply offering to re-ship or track.",
        },
        {
            "prompt": "Customer asks how to reset their password.",
            "expected_outcome": "",
        },
    ],
    "success_criteria": [
        "Reply addresses the customer's actual issue",
        "Tone matches the brand (friendly, concise)",
        "No forbidden promises (refunds/pricing) are made",
    ],
}


@pytest.fixture
def valid_spec_payload() -> dict:
    return dict(VALID_SPEC_PAYLOAD)


@pytest.fixture
def valid_spec() -> ClientSpec:
    return ClientSpec(
        goal="Triage inbound support emails and draft replies",
        preferences=("Friendly but concise tone",),
        constraints=("Never promise a refund",),
        example_tasks=(
            ExampleTask(
                prompt="Customer says order #1234 never arrived. Draft a reply.",
                expected_outcome="Apologetic reply offering to re-ship or track.",
            ),
            ExampleTask(prompt="Customer asks how to reset their password."),
        ),
        success_criteria=(
            "Reply addresses the customer's actual issue",
            "No forbidden promises are made",
        ),
    )
