from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pathlib import Path

from open_agent_compiler.model.core.mock_model import MockResponse
from open_agent_compiler.model.core.permissions_model import BashToolPermission, JsonToolPermission
from open_agent_compiler.model.core.test_model import ToolTest

SupportedScriptTypes = Literal['python', 'javascript', 'typescript']

class ScriptDefinition(BaseModel):
    target_file_path: Path
    source_file_path: Path | None
    source_file_type: SupportedScriptTypes | None
    script_contents: str | None

    @model_validator(mode='before')
    @classmethod
    def check_if_file_has_correct_extention(cls, data):
        if not isinstance(data, dict):
            return data
        
        #TODO
        # Check if the postfix .py, /ts, .tsx ect matches the list of types
        # Assign the type extention based on sufix

        return data

    @model_validator(mode='after')
    def verify_file_existance(self) -> 'ScriptDefinition':

        #TODO verify if the agent is actually having the file

        return self

    

class ToolScriptDefinition(BaseModel):
    paths: list[Path] | None
    scripts: list[ScriptDefinition] | None


class ToolDefinitionHeader(BaseModel):
    name: str
    description: str
    usage_explanation_long: str
    usage_explanation_short: str
    rules: list[str] 

class ToolDefinitionLogicJson(BaseModel):
    permission_json: JsonToolPermission
    positive_examples: list[str]
    negative_examples: list[str]
    mode_specific_rules: list[str]
    tool_scripts: list[ToolScriptDefinition]


class ToolDefinitionLogicBash(BaseModel):
    permission_bash: BashToolPermission
    positive_examples: list[str]
    negative_examples: list[str]
    mode_specific_rules: list[str]


class ToolDefinition(BaseModel):
    header: ToolDefinitionHeader
    json_tool: ToolDefinitionLogicJson | None = None
    bash_tool: ToolDefinitionLogicBash | None = None
    mock: MockResponse | None = None
    """Default mock for this tool. A MockProfile on the compile invocation
    overrides this on a per-tool basis; if neither is set the tool runs
    against real resources."""

    requires_resources: list[str] = []
    """Symbolic names of external resources this tool reads/writes (e.g.
    'goal_db', 'telegram_bot'). The active AccessProfile must bind every
    name; otherwise compilation fails. Empty list = no external resources."""

    tool_tests: list[ToolTest] = Field(
        default_factory=list,
        description=(
            "Test scenarios exercising this tool. Discovered recursively"
            " from every tool reachable through any registered agent."
        ),
    )