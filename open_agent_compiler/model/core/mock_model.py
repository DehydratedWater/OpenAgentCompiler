"""Mock surface for tools.

Two layers:

1. `MockResponse` — what a tool should return when invoked in mock mode.
   Either a fixed JSON payload, an echo of the input, or a reference to
   a Python callable (`module:callable`) that takes the validated input
   and returns the output dict.

2. `MockProfile` — a named bundle of `tool_name → MockResponse`. The
   CompileScript carries an optional active profile; when present, the
   compiler emits agents whose tool invocations resolve through the
   mock surface instead of hitting real resources.

Tools may also declare a *default* mock on their ToolDefinition.mock
field, which acts as a fallback when no profile overrides it. That
keeps simple cases (no resources, deterministic answers) one line of
config instead of needing a separate profile.

This module is intentionally storage-only — runtime resolution lives
in `open_agent_compiler.runtime` (ScriptTool) and the compiler's emission layer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MockKind = Literal["fixed", "echo", "callable", "sequence", "stateful_callable"]


class MockResponse(BaseModel):
    """How a mock invocation of a tool should resolve.

    kind:
      - "fixed": return `fixed_output` verbatim regardless of input.
      - "echo": return the input as the output (useful for pass-through
        scripts whose schema is identical input→output).
      - "callable": import `callable_spec` ("module:fn") and invoke it
        with the validated input model; the return value is used as the
        output. Callable specs are imported lazily at run time, never
        at compile time, so a missing dep does not break compilation.
      - "sequence": iterate `sequence` (a tuple of MockResponse), one
        per call. The N-th invocation of the tool resolves through
        sequence[N]; out-of-bounds calls reuse the last element so the
        scenario terminates cleanly rather than crashing. Use for
        mocked data streams: "first call returns batch A, second
        returns batch B, third returns empty."
      - "stateful_callable": same as "callable" but the function is
        invoked as fn(input, state) where `state` is a MockState
        carrying a call_index counter + a scratchpad dict that
        persists across invocations of the same tool within a test
        run. Use for monitoring agents whose mock needs to remember
        "what did I send last time".
    """

    model_config = ConfigDict(frozen=True)

    kind: MockKind = "fixed"
    fixed_output: dict[str, Any] | None = None
    callable_spec: str | None = None
    sequence: tuple["MockResponse", ...] = Field(
        default=(),
        description=(
            "For kind='sequence': the per-call MockResponses. The N-th"
            " invocation resolves through sequence[min(N, len-1)]."
        ),
    )
    description: str | None = Field(
        default=None,
        description="Human-readable note explaining what this mock represents.",
    )

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> "MockResponse":
        if self.kind == "fixed" and self.fixed_output is None:
            raise ValueError("MockResponse(kind='fixed') requires fixed_output")
        if self.kind == "callable" and not self.callable_spec:
            raise ValueError("MockResponse(kind='callable') requires callable_spec")
        if self.kind == "callable" and ":" not in (self.callable_spec or ""):
            raise ValueError(
                f"callable_spec must be 'module:callable', got {self.callable_spec!r}"
            )
        if self.kind == "stateful_callable" and not self.callable_spec:
            raise ValueError(
                "MockResponse(kind='stateful_callable') requires callable_spec"
            )
        if self.kind == "stateful_callable" and ":" not in (self.callable_spec or ""):
            raise ValueError(
                f"callable_spec must be 'module:callable', got {self.callable_spec!r}"
            )
        if self.kind == "sequence" and not self.sequence:
            raise ValueError(
                "MockResponse(kind='sequence') requires a non-empty sequence"
            )
        return self


class MockState(BaseModel):
    """Per-tool state threaded across calls within a test scenario.

    Passed to `stateful_callable` mock functions as the second argument.
    `call_index` increments per tool-name per scenario; `scratchpad`
    is a free-form dict the user's callable can read/write to
    remember context across calls (e.g. "what timestamp did I emit
    last", "running total", "is monitor in alert state").
    """

    model_config = ConfigDict(frozen=False)

    tool_name: str
    call_index: int = 0
    scratchpad: dict[str, Any] = Field(default_factory=dict)


class MockProfile(BaseModel):
    """A named bundle of mocks the compiler can apply to a test variant.

    A profile's `responses` map is keyed by tool name (matching
    `ToolDefinitionHeader.name`). When the compiler builds a test
    variant under this profile, each tool that has an entry here has
    its real invocation replaced by the mock resolution.

    Profiles compose: the runtime checks the active profile first, then
    falls back to the tool's own default mock if any, then errors if
    the tool requires mocking and neither is set.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    responses: dict[str, MockResponse] = Field(default_factory=dict)

    def resolve(self, tool_name: str) -> MockResponse | None:
        return self.responses.get(tool_name)
