"""InteractiveAgentSpec + dual-provider resolution.

The crux: the SAME AgentDefinition resolves to a DIFFERENT provider depending
on which profile you build with — a worker profile (opencode / z.ai) vs a
live profile (interactive / local OpenAI-compatible) — keyed on model_class.
"""

from __future__ import annotations

import pytest

from open_agent_compiler.interactive import build_interactive_spec, render_interactive_prompt
from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.model.core.split_profile import SplitProfile
from open_agent_compiler.model.core.tools_model import ToolDefinition, ToolDefinitionHeader


# --- presets: same logical classes, two providers ---------------------

ZAI_DEFAULT = ModelPreset(name="w-default", provider="zai-coding-plan", model_id="glm-4.6")
ZAI_FAST = ModelPreset(name="w-fast", provider="zai-coding-plan", model_id="glm-4.5-air")

LOCAL_DEFAULT = ModelPreset(
    name="l-default", provider="local", model_id="qwen2.5",
    sampling=SamplingDefaults(temperature=0.4),
    provider_options={"base_url": "http://localhost:8000/v1", "api_key_env": "LOCAL_LLM_KEY"},
)
LOCAL_FAST = ModelPreset(
    name="l-fast", provider="local", model_id="qwen2.5-3b",
    provider_options={"base_url": "http://localhost:8000/v1", "api_key_env": "LOCAL_LLM_KEY"},
)

WORKER_PROFILE = SplitProfile(
    name="worker", preset=ZAI_DEFAULT,
    class_map={"default": ZAI_DEFAULT, "fast": ZAI_FAST},
)
LIVE_PROFILE = SplitProfile(
    name="live", preset=LOCAL_DEFAULT,
    class_map={"default": LOCAL_DEFAULT, "fast": LOCAL_FAST},
)


def _agent(model_class="default", **kw) -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(agent_id="chat", name="chat"),
        usage_explanation_long="Steer the campaign.",
        usage_explanation_short="steer",
        system_prompt=kw.pop("system_prompt", "You are a helpful campaign-steering assistant."),
        model_class=model_class,
        **kw,
    )


def test_same_agent_resolves_to_different_providers_per_profile():
    agent = _agent()
    live = build_interactive_spec(agent=agent, live_profile=LIVE_PROFILE)
    worker = build_interactive_spec(agent=agent, live_profile=WORKER_PROFILE)

    # live → local OpenAI-compatible endpoint
    assert live.provider == "local"
    assert live.model_id == "qwen2.5"
    assert live.base_url == "http://localhost:8000/v1"
    assert live.api_key_env == "LOCAL_LLM_KEY"
    assert live.temperature == 0.4

    # worker → z.ai coding plan, no base_url (opencode handles it)
    assert worker.provider == "zai-coding-plan"
    assert worker.model_id == "glm-4.6"
    assert worker.base_url is None


def test_model_class_routing_picks_the_right_preset():
    fast = build_interactive_spec(agent=_agent(model_class="fast"), live_profile=LIVE_PROFILE)
    assert fast.model_id == "qwen2.5-3b"
    # unknown class falls back to default_class
    other = build_interactive_spec(agent=_agent(model_class="vision"), live_profile=LIVE_PROFILE)
    assert other.model_id == "qwen2.5"


def test_interactive_prompt_is_core_intent_without_opencode_scaffolding():
    agent = _agent(system_prompt="You are a terse copy critic.")
    p = render_interactive_prompt(agent)
    assert "terse copy critic" in p
    # none of the opencode runtime scaffolding leaks in
    for scaffold in ("STEP 0", "SECURITY POLICY", "via bash", "opencode", "todowrite"):
        assert scaffold not in p


def test_tools_are_collected_into_specs():
    tool = ToolDefinition(header=ToolDefinitionHeader(
        name="priority-manager", description="Read and update priorities.",
        usage_explanation_long="Manages the priority list.",
        usage_explanation_short="priorities", rules=[]))
    spec = build_interactive_spec(agent=_agent(extra_tools=[tool]), live_profile=LIVE_PROFILE)
    names = [t.name for t in spec.tools]
    assert "priority-manager" in names
    t = next(t for t in spec.tools if t.name == "priority-manager")
    assert t.description == "Read and update priorities."


def test_spec_is_frozen():
    spec = build_interactive_spec(agent=_agent(), live_profile=LIVE_PROFILE)
    with pytest.raises(Exception):
        spec.agent_id = "x"  # frozen
