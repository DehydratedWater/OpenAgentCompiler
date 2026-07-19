"""pi native tools: .pi/extensions/oac-tools.ts emission (registerTool)."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.compiler.native_tools import typebox_params_from_schema
from open_agent_compiler.compiler.script import CompileScript
from tests.compiler.test_native_tools import _registry as _weather_registry_helper  # noqa: F401
from tests.compiler.test_native_tools import _weather_tool
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry


def _registry(tmp_path: Path) -> AgentRegistry:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="demo", name="demo", description="demo"),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="You forecast weather.",
        extra_tools=[_weather_tool(tmp_path)],
    )
    aid = reg.register_agent("demo", agent, ModelParameters(model_name="m"))
    reg.register_template(TemplateTree(
        name="t", slots=[TemplateSlot(name="primary", default_agent_id=aid)]))
    reg.create_compilation_config(CompilationConfig(name="c", template_name="t"))
    return reg


def test_typebox_mapping() -> None:
    body = typebox_params_from_schema({
        "properties": {
            "city": {"type": "string", "description": "City name"},
            "days": {"type": "integer"},
            "mode": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["city"],
    })
    assert '"city": Type.String({"description": "City name"})' in body
    assert '"days": Type.Optional(Type.Integer())' in body
    assert 'Type.Union([Type.Literal("a"), Type.Literal("b")])' in body


def test_pi_native_emits_register_tool_extension(tmp_path: Path) -> None:
    target = tmp_path / "build"
    CompileScript(
        target=target, factory=lambda: _registry(tmp_path), config="c",
        dialect="pi", native_tools=True,
    ).run()
    ext = target / ".pi" / "extensions" / "oac-tools.ts"
    assert ext.exists()
    content = ext.read_text()
    assert "pi.registerTool({" in content
    assert '"weather"' in content
    assert 'runScript("scripts/weather.py", params)' in content
    assert '"--json"' in content  # the stdin contract in the shared helper
    assert 'from "@earendil-works/pi-coding-agent"' in content
    # The backing script compiled alongside.
    assert (target / "scripts" / "weather.py").exists()


def test_pi_without_flag_emits_no_extension(tmp_path: Path) -> None:
    target = tmp_path / "build2"
    CompileScript(
        target=target, factory=lambda: _registry(tmp_path), config="c",
        dialect="pi", native_tools=False,
    ).run()
    assert not (target / ".pi" / "extensions").exists()
