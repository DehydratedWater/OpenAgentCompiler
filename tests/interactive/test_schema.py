"""Rich tool schemas in the interactive tier — spec derivation + bindings."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.interactive.bindings import langchain_binding as lcb
from open_agent_compiler.interactive.schema import model_from_input_schema
from open_agent_compiler.interactive.spec import (
    InteractiveAgentSpec,
    ToolSpec,
    build_interactive_spec,
)
from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.model.core.permissions_model import (
    BashToolPermission,
    JsonToolPermission,
)
from open_agent_compiler.model.core.split_profile import SplitProfile
from open_agent_compiler.model.core.tools_model import (
    ScriptDefinition,
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
    ToolDefinitionLogicJson,
    ToolScriptDefinition,
)

_SCRIPT = '''\
from pydantic import BaseModel, Field
from open_agent_compiler.runtime import ScriptTool


class Input(BaseModel):
    city: str = Field(description="City name")
    days: int = 3


class Output(BaseModel):
    forecast: str


class WeatherTool(ScriptTool[Input, Output]):
    name = "weather"
    description = "Get a forecast."

    def execute(self, input: Input) -> Output:
        return Output(forecast=f"{input.city}:{input.days}")
'''


def _weather_tool(tmp_path: Path) -> ToolDefinition:
    source = tmp_path / "weather_src.py"
    source.write_text(_SCRIPT)
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="weather", description="Get a forecast.",
            usage_explanation_long="l", usage_explanation_short="s", rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=["python scripts/weather.py *"],
            ),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
        ),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(tool_name="custom_tool", value="allow"),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
            tool_scripts=[ToolScriptDefinition(paths=None, scripts=[
                ScriptDefinition(
                    target_file_path=Path("scripts/weather.py"),
                    source_file_path=source,
                    source_file_type="python",
                    script_contents=None,
                ),
            ])],
        ),
    )


def _live_profile() -> SplitProfile:
    preset = ModelPreset(
        name="live", provider="local", model_id="m",
        sampling=SamplingDefaults(temperature=0.1),
    )
    return SplitProfile(name="live", preset=preset, class_map={"default": preset})


# ---- model_from_input_schema ------------------------------------------


def test_model_from_schema_maps_types_and_requiredness() -> None:
    model = model_from_input_schema("t", {
        "properties": {
            "city": {"type": "string", "description": "City name"},
            "days": {"type": "integer", "default": 3},
        },
        "required": ["city"],
    })
    assert model is not None
    fields = model.model_fields
    assert fields["city"].is_required()
    assert fields["city"].description == "City name"
    assert not fields["days"].is_required()
    assert fields["days"].default == 3
    parsed = model(city="Krakow")
    assert parsed.city == "Krakow" and parsed.days == 3


def test_model_from_schema_returns_none_without_properties() -> None:
    assert model_from_input_schema("t", None) is None
    assert model_from_input_schema("t", {}) is None
    assert model_from_input_schema("t", {"properties": {}}) is None


# ---- spec derivation ---------------------------------------------------


def test_build_interactive_spec_derives_input_schema(tmp_path: Path) -> None:
    agent = AgentDefinition(
        header=AgentHeader(agent_id="a", name="a", description="d"),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="p",
        extra_tools=[_weather_tool(tmp_path)],
    )
    spec = build_interactive_spec(agent=agent, live_profile=_live_profile())
    schema = spec.tools[0].input_schema
    assert schema["properties"]["city"]["type"] == "string"
    assert schema["properties"]["days"]["default"] == 3


# ---- bindings use the rich schema --------------------------------------


def _spec_with_schema() -> InteractiveAgentSpec:
    preset = ModelPreset(name="l", provider="local", model_id="m",
                         sampling=SamplingDefaults(temperature=0.1))
    return InteractiveAgentSpec(
        agent_id="x", model=preset, system_prompt="p",
        tools=(ToolSpec(
            name="weather", description="d",
            input_schema={
                "properties": {"city": {"type": "string"},
                               "days": {"type": "integer", "default": 3}},
                "required": ["city"],
            },
        ),),
    )


def test_langchain_structured_tool_passes_typed_args() -> None:
    calls = []
    tool = lcb.to_langchain_tools(
        _spec_with_schema(), lambda n, a: calls.append((n, a)) or "ok",
    )[0]
    out = tool.invoke({"city": "Krakow", "days": 5})
    assert out == "ok"
    assert calls == [("weather", {"city": "Krakow", "days": 5})]


def test_langchain_schemaless_tool_keeps_input_contract() -> None:
    calls = []
    preset = ModelPreset(name="l", provider="local", model_id="m",
                         sampling=SamplingDefaults(temperature=0.1))
    spec = InteractiveAgentSpec(
        agent_id="x", model=preset, system_prompt="p",
        tools=(ToolSpec(name="plain", description="d"),),
    )
    tool = lcb.to_langchain_tools(spec, lambda n, a: calls.append((n, a)) or "ok")[0]
    tool.invoke("query")
    assert calls == [("plain", {"input": "query"})]


def test_pydantic_ai_tool_gets_typed_signature() -> None:
    import inspect

    import pytest

    pytest.importorskip("pydantic_ai")
    from open_agent_compiler.interactive.bindings import pydantic_ai_binding as pab

    calls = []
    tool = pab.to_pydantic_ai_tools(
        _spec_with_schema(), lambda n, a: calls.append((n, a)) or "ok",
    )[0]
    sig = inspect.signature(tool.function)
    assert set(sig.parameters) == {"city", "days"}
    assert tool.function(city="Krakow", days=2) == "ok"
    assert calls == [("weather", {"city": "Krakow", "days": 2})]
