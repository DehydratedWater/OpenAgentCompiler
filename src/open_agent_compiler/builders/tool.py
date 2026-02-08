"""Fluent builder for ToolDefinition."""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
from typing import TYPE_CHECKING

from open_agent_compiler._types import (
    ActionDefinition,
    ParameterDefinition,
    StreamFormat,
    ToolDefinition,
    UsageExample,
)
from open_agent_compiler.builders._base import Builder

if TYPE_CHECKING:
    from open_agent_compiler.runtime import ScriptTool


# Mapping from Python type annotations to param_type strings
_ANNOTATION_MAP: dict[type | str, str] = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
}


class ToolBuilder(Builder[ToolDefinition]):
    """Build a ToolDefinition with a fluent API.

    Supports two introspection entry points that use Pydantic models
    as the single source of truth:
    - ``from_script(file_path)`` — dynamically import a handler file
    - ``from_handler(handler_cls, file_path)`` — use an already-imported class
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> ToolBuilder:
        self._name: str | None = None
        self._description: str | None = None
        self._actions: list[ActionDefinition] = []
        self._script_files: list[str] = []
        self._examples: list[UsageExample] = []
        return self

    def name(self, name: str) -> ToolBuilder:
        self._name = name
        return self

    def description(self, description: str) -> ToolBuilder:
        self._description = description
        return self

    def action(self, action: ActionDefinition) -> ToolBuilder:
        self._actions.append(action)
        return self

    def script_file(self, path: str) -> ToolBuilder:
        self._script_files.append(path)
        return self

    def example(self, name: str, description: str, command: str) -> ToolBuilder:
        """Add a named usage example to the tool."""
        self._examples.append(UsageExample(name, description, command))
        return self

    def from_command(self, command: str) -> ToolBuilder:
        """Set up an action from an arbitrary bash command (no script file).

        Only creates the action.  Call ``.name()`` and ``.description()``
        separately to set the tool identity.

        Parameters
        ----------
        command:
            The bash command, e.g. ``"nvidia-smi"`` or ``"docker ps -a"``.
        """
        self._actions = [
            ActionDefinition(
                command_pattern=command,
                description=command,
                usage_example=command,
            ),
        ]
        self._script_files = []
        return self

    def from_script(self, file_path: str) -> ToolBuilder:
        """Dynamically import *file_path* and extract ScriptTool metadata."""
        from open_agent_compiler.runtime import ScriptTool as _ScriptTool

        module_name = f"_oac_dynamic_{file_path.replace('/', '_').replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {file_path!r}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find the ScriptTool subclass in the module
        handler_cls: type[ScriptTool] | None = None  # type: ignore[type-arg]
        for _attr_name, obj in inspect.getmembers(module, inspect.isclass):
            if obj is not _ScriptTool and issubclass(obj, _ScriptTool):
                handler_cls = obj
                break

        if handler_cls is None:
            raise ImportError(f"No ScriptTool subclass found in {file_path!r}")

        self._populate_from_handler(handler_cls, file_path)
        return self

    def from_handler(
        self,
        handler_cls: type[ScriptTool],  # type: ignore[type-arg]
        file_path: str,
    ) -> ToolBuilder:
        """Extract metadata from an already-imported ScriptTool subclass."""
        self._populate_from_handler(handler_cls, file_path)
        return self

    def _populate_from_handler(
        self,
        handler_cls: type[ScriptTool],  # type: ignore[type-arg]
        file_path: str,
    ) -> None:
        """Extract actions and script files from a ScriptTool subclass.

        Does NOT set name or description — use ``.name()`` and
        ``.description()`` on the builder.
        """
        basename = os.path.basename(file_path)
        self._script_files = [basename]

        # Extract parameters from Pydantic Input model
        input_type = handler_cls._get_input_type()
        params: list[ParameterDefinition] = []
        for field_name, field_info in input_type.model_fields.items():
            annotation = field_info.annotation
            param_type = _ANNOTATION_MAP.get(annotation, "str")  # type: ignore[arg-type]
            if annotation not in _ANNOTATION_MAP and hasattr(annotation, "__name__"):
                param_type = _ANNOTATION_MAP.get(annotation.__name__, "str")  # type: ignore[union-attr]

            default_val: str | None = None
            if not field_info.is_required() and field_info.default is not None:
                default_val = str(field_info.default)

            params.append(
                ParameterDefinition(
                    name=field_name,
                    description=field_info.description or "",
                    param_type=param_type,
                    required=field_info.is_required(),
                    default=default_val,
                )
            )

        # Build description parts
        desc = getattr(handler_cls, "description", "") or ""

        # Stream config info
        stream_fmt = getattr(handler_cls, "stream_format", None)
        stream_fld = getattr(handler_cls, "stream_field", None)
        stream_info = ""
        if stream_fmt is not None and stream_fld is not None:
            fmt_val = StreamFormat(stream_fmt).value
            stream_info = (
                f" Supports stdin streaming (`{stream_fld}` via stdin as {fmt_val})."
            )

        action_desc = desc + stream_info

        # Build usage example from parameters
        args_parts: list[str] = []
        for p in params:
            if p.required:
                args_parts.append(f'--{p.name} "<{p.param_type}>"')
            else:
                args_parts.append(f"--{p.name} <{p.param_type}>")
        args_str = " ".join(args_parts)

        command_pattern = f"uv run scripts/{basename} *"
        usage_example = f"uv run scripts/{basename} {args_str}"

        self._actions = [
            ActionDefinition(
                command_pattern=command_pattern,
                description=action_desc,
                usage_example=usage_example,
            ),
        ]

    def build(self) -> ToolDefinition:
        if not self._name:
            raise ValueError("ToolDefinition requires a name")
        if not self._description:
            raise ValueError("ToolDefinition requires a description")
        if not self._actions:
            raise ValueError("ToolDefinition requires at least one action")

        return ToolDefinition(
            name=self._name,
            description=self._description,
            actions=tuple(self._actions),
            script_files=tuple(self._script_files),
            examples=tuple(self._examples),
        )
