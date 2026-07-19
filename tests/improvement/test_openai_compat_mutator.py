"""OpenAICompatMutatorClient — the out-of-the-box LLM rewriter client."""

from __future__ import annotations

from open_agent_compiler.improvement import (
    LLMPromptRewriter,
    OpenAICompatMutatorClient,
)
from open_agent_compiler.improvement.mutators import MutationContext
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.interactive.runner import ChatResponse


class _ScriptedChat:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    def complete(self, *, messages, tools, model, **params):
        self.calls.append({"messages": messages, "model": model,
                           "params": params})
        return ChatResponse(content=self.content)


def test_rewrite_carries_guidance_context_and_target() -> None:
    chat = _ScriptedChat("BETTER PROMPT")
    client = OpenAICompatMutatorClient(model_id="m", client=chat)
    out = client.rewrite(
        "old prompt", "make it concise", context={"failures": ["too long"]},
    )
    assert out == "BETTER PROMPT"
    user = chat.calls[0]["messages"][1]["content"]
    assert "make it concise" in user
    assert "too long" in user
    assert "old prompt" in user
    assert chat.calls[0]["model"] == "m"


def test_rewrite_strips_code_fences_and_honors_model_override() -> None:
    chat = _ScriptedChat("```text\nREWRITTEN\n```")
    client = OpenAICompatMutatorClient(model_id="m", client=chat)
    assert client.rewrite("x", "g", model="override") == "REWRITTEN"
    assert chat.calls[0]["model"] == "override"


def test_from_env_prefers_mutator_vars_then_live(monkeypatch) -> None:
    for var in ("OAC_MUTATOR_MODEL", "OAC_MUTATOR_BASE_URL",
                "OAC_MUTATOR_API_KEY", "LIVE_MODEL_ID", "LIVE_BASE_URL",
                "LIVE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert OpenAICompatMutatorClient.from_env() is None

    monkeypatch.setenv("LIVE_MODEL_ID", "live-model")
    client = OpenAICompatMutatorClient.from_env()
    assert client is not None and client.model_id == "live-model"

    monkeypatch.setenv("OAC_MUTATOR_MODEL", "strong-model")
    client = OpenAICompatMutatorClient.from_env()
    assert client.model_id == "strong-model"


def test_works_as_llm_for_prompt_rewriter() -> None:
    chat = _ScriptedChat("ADAPTED")
    client = OpenAICompatMutatorClient(model_id="m", client=chat)
    parent = ComponentVersion.of(
        component_id="a", kind="agent",
        definition={"system_prompt": "old"},
    )
    child = LLMPromptRewriter().mutate(parent, MutationContext(llm=client))
    assert child is not None
    assert child.definition["system_prompt"] == "ADAPTED"
