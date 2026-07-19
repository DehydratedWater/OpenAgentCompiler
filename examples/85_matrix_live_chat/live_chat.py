"""Live chat over the matrix: one realtime agent that can spin up ANY of
the four compiled worker variants — and uses the interactive-tuned prompt.

The realtime orchestrator is built from the SAME definitions
(`registry(target="interactive")` merges the interactive autoloop
winner), holds one `spawn_worker` tool, and routes each spawn through
`get_runner(harness, build_dir)` — so `pi × smart` and `opencode × fast`
workers are equally one tool call away from the same chat.

Offline by default (scripted chat model + fake workers) so the wiring
runs anywhere; pass --live to talk to your real local provider and the
real `opencode` / `pi` binaries against the build_matrix.py outputs.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

from agents import _orchestrator  # noqa: E402
from open_agent_compiler.improvement import apply_promoted_to_tree, get_runner  # noqa: E402
from open_agent_compiler.interactive.runner import ChatResponse, ChatToolCall, run_interactive  # noqa: E402
from open_agent_compiler.interactive.spec import InteractiveAgentSpec, ToolSpec  # noqa: E402
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults  # noqa: E402

LIVE = "--live" in sys.argv

# The four worker coordinates the chat can dispatch to.
MATRIX = {
    ("opencode", "fast"): ("build_opencode", "primary"),
    ("opencode", "smart"): ("build_opencode", "primary-smart"),
    ("pi", "fast"): ("build_pi", "primary"),
    ("pi", "smart"): ("build_pi", "primary-smart"),
}


def spawn_worker(name: str, args: dict) -> str:
    """ToolRunner for the realtime agent's `spawn_worker` tool.

    args: {"harness": "opencode"|"pi", "model": "fast"|"smart",
           "prompt": "..."} — parsed from the model's single input string
    in offline mode for simplicity.
    """
    raw = str(args.get("input", ""))
    harness = "pi" if "pi" in raw else "opencode"
    model = "smart" if "smart" in raw else "fast"
    build_dir, agent = MATRIX[(harness, model)]
    if not LIVE:
        return (f"[offline] would run `{agent}` in {build_dir}/ via the"
                f" {harness} runner")
    runner = get_runner(harness, HERE / build_dir)
    result = runner.run(agent_name=agent, prompt=raw, timeout_s=180)
    if result.error:
        return f"worker failed: {result.error}"
    return result.final_text()


class _ScriptedClient:
    """Offline chat model: asks for one worker spawn, then answers."""

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, messages, tools, model, **params):
        self.turn += 1
        if self.turn == 1:
            return ChatResponse(tool_calls=[ChatToolCall(
                id="1", name="spawn_worker",
                args={"input": "pi smart: summarize+critique the user claim"},
            )])
        tool_result = next(
            m["content"] for m in reversed(messages) if m.get("role") == "tool"
        )
        return ChatResponse(
            content=f"Dispatched a worker for you. Worker said: {tool_result}"
        )


def main() -> None:
    # Same tree, interactive target: the autoloop winner promoted under
    # target="interactive" lands in this prompt (and ONLY this one).
    orch = apply_promoted_to_tree(
        _orchestrator(), project_root=HERE, target="interactive",
    )
    spec = InteractiveAgentSpec(
        agent_id="orchestrator",
        model=ModelPreset(
            name="live", provider="local-vllm", model_id="my-local-model",
            sampling=SamplingDefaults(temperature=0.4),
            provider_options={"base_url": "http://localhost:8000/v1"},
        ),
        system_prompt=orch.system_prompt + (
            "\n\nYou can dispatch long-running workers with the"
            " `spawn_worker` tool: say which harness (opencode/pi) and"
            " model (fast/smart) plus the task."
        ),
        tools=(ToolSpec(
            name="spawn_worker",
            description="Run a compiled worker: 'opencode|pi fast|smart: <task>'.",
        ),),
    )
    result = run_interactive(
        spec,
        "Evaluate this claim thoroughly: remote work increases productivity.",
        tool_runner=spawn_worker,
        client=None if LIVE else _ScriptedClient(),
    )
    print("prompt in use:", spec.system_prompt.splitlines()[0][:70])
    print("tool calls:", [(c.name, c.args) for c in result.tool_calls])
    print("chat reply:", result.output_text)


if __name__ == "__main__":
    main()
