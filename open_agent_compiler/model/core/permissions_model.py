from dataclasses import dataclass, field
from typing import Literal, Union

ToolScope = Literal['*']
PermissionType = Literal['allow', 'deny', 'ask']
DefaultTools = Literal[
    'custom_tool',
    'read',
    'edit',
    'patch',
    'write',
    'mcp',
    'bash',
    'glob',
    'lsp',
    'skill',
    'todowrite',
    'webfetch',
    'websearch',
    'external_directory',
    'doom_loop',
    'question',
]


@dataclass
class Permission:
    tool_name: Union[DefaultTools, str]


@dataclass
class ToolPermission(Permission):
    scope: Union[ToolScope, str]
    value: PermissionType


@dataclass
class JsonToolPermission(ToolPermission):
    scope: Literal['custom_tool'] = 'custom_tool'
    value: PermissionType = 'allow'

    def __post_init__(self) -> None:
        if self.scope != 'custom_tool':
            raise ValueError(
                f"JsonToolPermission scope must be 'custom_tool', got '{self.scope}'"
            )


@dataclass
class BashToolPermission(ToolPermission):
    scope: Literal['bash'] = 'bash'
    value: PermissionType = 'allow'
    allowed_commands: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.scope != 'bash':
            raise ValueError(
                f"BashToolPermission scope must be 'bash', got '{self.scope}'"
            )
