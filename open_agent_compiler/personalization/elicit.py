"""Chat transcript → validated ClientSpec, via the opencode teacher.

`elicit_client_spec(chat_transcript, teacher)` asks the injected TEACHER (the
`OpencodeMutatorClient` / GLM-via-opencode path — NEVER a raw provider API) to
read the client's chat and emit a structured spec as JSON, then parses and
validates it into a `ClientSpec`.

The teacher call is the ONLY IO seam in Phase D. In tests it is always a fake
exposing `.complete(system, user)` that returns canned JSON — no live opencode,
qwen, z.ai, or network is ever touched here. On malformed teacher output (no
JSON object, unparseable JSON, or a payload that fails `ClientSpec` validation)
a clear `SpecElicitationError` is raised.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from open_agent_compiler.personalization.spec import ClientSpec, ExampleTask


class TeacherClient(Protocol):
    """The minimal seam used for elicitation: one routed completion.

    `OpencodeMutatorClient.complete` satisfies this exactly. Tests inject a fake
    returning canned JSON.
    """

    def complete(self, system: str, user: str, *, model: str | None = ...) -> str:
        ...


class SpecElicitationError(ValueError):
    """Raised when the teacher's output cannot become a valid ClientSpec."""


_ELICIT_SYSTEM = (
    "You are an intake analyst for a per-client AI-agent platform. Read the"
    " client's chat transcript and distil it into a STRUCTURED SPEC describing the"
    " agent they want. Capture their goal, soft preferences, hard constraints,"
    " concrete example tasks (real inputs the agent should handle, each with an"
    " optional note on what a good result looks like), and explicit success"
    " criteria (what THEY would call a good job). Do not invent capabilities they"
    " did not ask for. Respond with STRICT JSON ONLY — no preamble, no markdown"
    " fences — matching exactly this shape:\n"
    "{\n"
    '  "goal": "<one sentence>",\n'
    '  "preferences": ["<pref>", ...],\n'
    '  "constraints": ["<constraint>", ...],\n'
    '  "example_tasks": [\n'
    '    {"prompt": "<a concrete task input>",'
    ' "expected_outcome": "<optional note, or empty string>"}, ...\n'
    "  ],\n"
    '  "success_criteria": ["<what good looks like>", ...]\n'
    "}"
)


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Pull the first top-level JSON object out of `raw`; raise on failure."""
    if not raw or not raw.strip():
        raise SpecElicitationError("teacher returned empty output")
    text = raw.strip()
    # Tolerate accidental ```json fences even though we asked for none.
    text = re.sub(r"^```[a-zA-Z0-9]*\n?|\n?```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise SpecElicitationError(
            f"no JSON object found in teacher output: {raw[:200]!r}"
        )
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise SpecElicitationError(
            f"teacher output is not valid JSON: {exc}"
        ) from exc
    if not isinstance(obj, dict):
        raise SpecElicitationError(
            f"teacher JSON is not an object: {type(obj).__name__}"
        )
    return obj


def _as_str_tuple(value: Any, field: str) -> tuple[str, ...]:
    """Coerce a JSON list-of-strings into a clean tuple; tolerate a bare string."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if not isinstance(value, list):
        raise SpecElicitationError(f"{field!r} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SpecElicitationError(
                f"{field!r} entries must be strings, got {type(item).__name__}"
            )
        if item.strip():
            out.append(item)
    return tuple(out)


def _as_example_tasks(value: Any) -> tuple[ExampleTask, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SpecElicitationError("'example_tasks' must be a list")
    tasks: list[ExampleTask] = []
    for i, item in enumerate(value):
        if isinstance(item, str):
            prompt, expected = item, ""
        elif isinstance(item, dict):
            prompt = item.get("prompt") or item.get("input") or ""
            expected = item.get("expected_outcome") or item.get("expected") or ""
        else:
            raise SpecElicitationError(
                f"example_tasks[{i}] must be a string or object,"
                f" got {type(item).__name__}"
            )
        if not isinstance(prompt, str) or not prompt.strip():
            # Skip empty entries rather than fail the whole elicitation.
            continue
        tasks.append(
            ExampleTask(prompt=prompt, expected_outcome=str(expected or ""))
        )
    return tuple(tasks)


def parse_client_spec(raw: str) -> ClientSpec:
    """Parse a teacher's raw JSON string into a validated ClientSpec.

    Raises `SpecElicitationError` on any malformed/invalid payload. Pure — no IO.
    """
    obj = _extract_json_object(raw)
    goal = obj.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise SpecElicitationError("'goal' is required and must be a non-empty string")
    try:
        return ClientSpec(
            goal=goal,
            preferences=_as_str_tuple(obj.get("preferences"), "preferences"),
            constraints=_as_str_tuple(obj.get("constraints"), "constraints"),
            example_tasks=_as_example_tasks(obj.get("example_tasks")),
            success_criteria=_as_str_tuple(
                obj.get("success_criteria"), "success_criteria"
            ),
        )
    except ValueError as exc:
        # ClientSpec / ExampleTask validation failures → a clear elicitation error.
        if isinstance(exc, SpecElicitationError):
            raise
        raise SpecElicitationError(f"invalid ClientSpec: {exc}") from exc


def elicit_client_spec(
    chat_transcript: str,
    teacher: TeacherClient,
    *,
    model: str | None = None,
    require_usable: bool = False,
) -> ClientSpec:
    """Extract a validated ClientSpec from a chat transcript via the teacher.

    `teacher` must expose `.complete(system, user, model=...)` routed through
    opencode (`OpencodeMutatorClient`); it is the only IO seam and is mocked in
    tests. Raises `SpecElicitationError` on empty/malformed teacher output. When
    `require_usable=True`, also enforces the stronger 'usable' contract (≥1
    example_task and ≥1 success_criterion) before returning.
    """
    if not chat_transcript or not chat_transcript.strip():
        raise SpecElicitationError("chat_transcript is empty")
    user = (
        "CLIENT CHAT TRANSCRIPT:\n"
        f"{chat_transcript.strip()}\n\n"
        "Return the spec JSON now."
    )
    raw = teacher.complete(_ELICIT_SYSTEM, user, model=model)
    spec = parse_client_spec(raw)
    if require_usable:
        spec.require_usable()
    return spec


__all__ = [
    "TeacherClient",
    "SpecElicitationError",
    "parse_client_spec",
    "elicit_client_spec",
]
