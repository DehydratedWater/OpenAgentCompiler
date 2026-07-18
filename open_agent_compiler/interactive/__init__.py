"""Interactive target — the second way to use a framework agent.

The framework's primary target compiles an `AgentDefinition` to **opencode
worker** artifacts (`.opencode/agents/*.md`): long-running, tool-using,
side-effecting agents run by an external runtime, fire-and-forget.

This package adds the **interactive target**: from the *same*
`AgentDefinition` it derives a runtime-agnostic `InteractiveAgentSpec`
(model + system prompt + tool specs + optional output schema) that thin
*bindings* (LangChain, raw SDK, …) turn into a streaming, request/response
agent for the dynamic/chat layer.

Crucially the two targets **share every primitive** — definitions, tools,
skills, model presets, variants/split-profiles, and the test/improve loop —
and only diverge at the backend. A tool or prompt optimised once in the
testable worker world binds straight into the interactive agent.

Dual providers fall out of the existing machinery: a *worker* `SplitProfile`
maps `model_class → preset` for opencode (e.g. z.ai coding plan), while a
*live* `SplitProfile` maps the same `model_class → preset` for the
interactive binding (e.g. a local OpenAI-compatible qwen). Same definition,
two provider resolutions.
"""

from open_agent_compiler.interactive.events import (
    CallbackSink,
    CollectingSink,
    Event,
    EventEmitter,
    EventKind,
    EventSink,
    NullSink,
    QueueSink,
    as_sink,
    invoke_runner,
    runner_accepts_emitter,
)
from open_agent_compiler.interactive.prompt import render_interactive_prompt
from open_agent_compiler.interactive.runner import (
    ChatClient,
    ChatResponse,
    ChatToolCall,
    MissingDependencyError,
    OpenAICompatClient,
    RunResult,
    run_interactive,
)
from open_agent_compiler.interactive.spec import (
    InteractiveAgentSpec,
    ToolSpec,
    build_interactive_spec,
)

__all__ = [
    "InteractiveAgentSpec",
    "ToolSpec",
    "build_interactive_spec",
    "render_interactive_prompt",
    # in-process runner (framework-owned tool loop; openai imported lazily)
    "ChatClient",
    "ChatResponse",
    "ChatToolCall",
    "MissingDependencyError",
    "OpenAICompatClient",
    "RunResult",
    "run_interactive",
    # event sink / emitter (optional; used by the LangChain binding + workflows)
    "Event",
    "EventKind",
    "EventSink",
    "NullSink",
    "CallbackSink",
    "CollectingSink",
    "QueueSink",
    "as_sink",
    "EventEmitter",
    "runner_accepts_emitter",
    "invoke_runner",
]
