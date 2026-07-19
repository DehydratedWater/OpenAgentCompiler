"""Native tool-calling emission: TS shims (opencode), MCP route (claude/codex)."""

from __future__ import annotations

import json
from pathlib import Path

from open_agent_compiler.compiler.native_tools import zod_args_from_schema
from open_agent_compiler.compiler.script import CompileScript
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.permissions_model import (
    BashToolPermission,
    JsonToolPermission,
)
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
    city: str = Field(description="City name to look up")
    days: int = 3
    verbose: bool = False


class Output(BaseModel):
    forecast: str


class WeatherTool(ScriptTool[Input, Output]):
    name = "weather"
    description = "Get a weather forecast."

    def execute(self, input: Input) -> Output:
        return Output(forecast=f"{input.city}: sunny for {input.days} days")


if __name__ == "__main__":
    WeatherTool.run()
'''


def _weather_tool(tmp_path: Path) -> ToolDefinition:
    source = tmp_path / "weather_src.py"
    source.write_text(_SCRIPT)
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="weather", description="Get a weather forecast.",
            usage_explanation_long="long", usage_explanation_short="short",
            rules=[],
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
            tool_scripts=[ToolScriptDefinition(
                paths=None,
                scripts=[ScriptDefinition(
                    target_file_path=Path("scripts/weather.py"),
                    source_file_path=source,
                    source_file_type="python",
                    script_contents=None,
                )],
            )],
        ),
    )


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


def _compile(tmp_path: Path, dialect: str, *, native: bool = True) -> Path:
    target = tmp_path / f"build_{dialect}_{native}"
    CompileScript(
        target=target, factory=lambda: _registry(tmp_path), config="c",
        dialect=dialect, native_tools=native,
    ).run()
    return target


# ---- zod mapping -------------------------------------------------------


def test_zod_args_mapping() -> None:
    schema = {
        "properties": {
            "city": {"type": "string", "description": "City name"},
            "days": {"type": "integer"},
            "verbose": {"type": "boolean"},
            "mode": {"type": "string", "enum": ["a", "b"]},
            "extra": {"type": "object"},
        },
        "required": ["city"],
    }
    args = zod_args_from_schema(schema)
    assert '"city": tool.schema.string().describe("City name"),' in args
    assert '"days": tool.schema.number().int().optional(),' in args
    assert '"verbose": tool.schema.boolean().optional(),' in args
    assert '"mode": tool.schema.enum(["a", "b"]).optional(),' in args
    assert '"extra": tool.schema.any().optional(),' in args


# ---- opencode: TS shims ------------------------------------------------


def test_opencode_native_emits_ts_shim(tmp_path: Path) -> None:
    target = _compile(tmp_path, "opencode")
    shim = target / ".opencode" / "tool" / "weather.ts"
    assert shim.exists()
    content = shim.read_text()
    assert 'from "@opencode-ai/plugin"' in content
    assert '"scripts/weather.py", "--json"' in content
    # Schema derived from the real Pydantic Input model.
    assert '"city": tool.schema.string()' in content
    assert '"days": tool.schema.number().int().optional()' in content
    # The backing script itself was compiled next to it.
    assert (target / "scripts" / "weather.py").exists()


def test_opencode_without_flag_emits_no_shims(tmp_path: Path) -> None:
    target = _compile(tmp_path, "opencode", native=False)
    assert not (target / ".opencode" / "tool").exists()


# ---- claude: MCP server + .mcp.json ------------------------------------


def test_claude_native_emits_mcp_server_and_config(tmp_path: Path) -> None:
    target = _compile(tmp_path, "claude")
    assert (target / "scripts" / "mcp_tools_server.py").exists()
    config = json.loads((target / ".mcp.json").read_text())
    server = config["mcpServers"]["oac-tools"]
    assert server["command"] == "python3"
    assert server["args"] == ["scripts/mcp_tools_server.py"]
    # No stray TS shims in the claude tree.
    assert not (target / ".claude" / "tool").exists()


# ---- codex: MCP block appended to agent TOMLs --------------------------


def test_codex_native_appends_mcp_server_block(tmp_path: Path) -> None:
    import tomllib

    target = _compile(tmp_path, "codex")
    assert (target / "scripts" / "mcp_tools_server.py").exists()
    data = tomllib.loads(
        (target / ".codex" / "agents" / "primary.toml").read_text()
    )
    assert data["mcp_servers"]["oac-tools"]["command"] == "python3"


def test_mcp_server_template_is_valid_python(tmp_path: Path) -> None:
    import ast

    target = _compile(tmp_path, "claude")
    ast.parse((target / "scripts" / "mcp_tools_server.py").read_text())
