"""run_interactive_async — the framework loop off the event loop thread."""

from __future__ import annotations

import asyncio

from open_agent_compiler.interactive.runner import (
    ChatResponse,
    run_interactive_async,
)
from open_agent_compiler.interactive.spec import InteractiveAgentSpec
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults


class _Client:
    def complete(self, *, messages, tools, model, **params):
        return ChatResponse(content="async ok")


def _spec() -> InteractiveAgentSpec:
    return InteractiveAgentSpec(
        agent_id="chat",
        model=ModelPreset(name="l", provider="local", model_id="m",
                          sampling=SamplingDefaults(temperature=0.1)),
        system_prompt="p",
    )


def test_async_runner_returns_same_result_shape() -> None:
    result = asyncio.run(run_interactive_async(_spec(), "hi", client=_Client()))
    assert result.output_text == "async ok"
    assert result.error is None


def test_async_runners_run_concurrently() -> None:
    import threading
    import time

    starts: list[float] = []

    class _Slow:
        def complete(self, *, messages, tools, model, **params):
            starts.append(time.monotonic())
            time.sleep(0.15)
            return ChatResponse(content=threading.current_thread().name)

    async def _two():
        return await asyncio.gather(
            run_interactive_async(_spec(), "a", client=_Slow()),
            run_interactive_async(_spec(), "b", client=_Slow()),
        )

    t0 = time.monotonic()
    results = asyncio.run(_two())
    elapsed = time.monotonic() - t0
    assert len(results) == 2
    # Overlapping, not serialized: two 0.15s turns in well under 0.3s.
    assert elapsed < 0.28
