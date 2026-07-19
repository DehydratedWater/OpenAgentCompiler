from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pathlib import Path

from open_agent_compiler.model.core.mock_model import MockResponse
from open_agent_compiler.model.core.permissions_model import BashToolPermission, JsonToolPermission
from open_agent_compiler.model.core.test_model import ToolTest

SupportedScriptTypes = Literal['python', 'javascript', 'typescript']

_SUFFIX_TO_SCRIPT_TYPE: dict[str, str] = {
    '.py': 'python',
    '.js': 'javascript',
    '.mjs': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
}


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

        target = data.get('target_file_path')
        suffix = Path(str(target)).suffix.lower() if target else ''
        inferred = _SUFFIX_TO_SCRIPT_TYPE.get(suffix)
        declared = data.get('source_file_type')
        if declared is None:
            if inferred is not None:
                data['source_file_type'] = inferred
        elif inferred is not None and declared != inferred:
            raise ValueError(
                f"source_file_type={declared!r} does not match the"
                f" {suffix!r} extension of {target}"
                f" (expected {inferred!r})"
            )
        return data

    @model_validator(mode='after')
    def verify_file_existance(self) -> 'ScriptDefinition':
        if self.script_contents is None and self.source_file_path is None:
            raise ValueError(
                f"script {self.target_file_path} carries no content:"
                " provide script_contents or source_file_path"
            )
        if (
            self.script_contents is None
            and self.source_file_path is not None
            and self.source_file_path.is_absolute()
            and not self.source_file_path.exists()
        ):
            raise ValueError(
                f"source file {self.source_file_path} does not exist"
            )
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