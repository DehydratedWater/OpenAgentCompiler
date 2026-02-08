"""Fluent builder for ToolDefinition."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from typing import TYPE_CHECKING

from open_agent_compiler._types import (
    ParameterDefinition,
    StreamFormat,
    ToolDefinition,
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
        self._file_path: str | None = None
        self._parameters: list[ParameterDefinition] = []
        self._stream_format: StreamFormat | None = None
        self._stream_field: str | None = None
        return self

    def name(self, name: str) -> ToolBuilder:
        self._name = name
        return self

    def description(self, description: str) -> ToolBuilder:
        self._description = description
        return self

    def file_path(self, file_path: str) -> ToolBuilder:
        self._file_path = file_path
        return self

    def parameter(self, param: ParameterDefinition) -> ToolBuilder:
        self._parameters.append(param)
        return self

    def stream_format(self, fmt: StreamFormat) -> ToolBuilder:
        self._stream_format = fmt
        return self

    def stream_field(self, field: str) -> ToolBuilder:
        self._stream_field = field
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
        """Extract ToolDefinition fields from a ScriptTool subclass."""
        self._name = getattr(handler_cls, "name", None)
        self._description = getattr(handler_cls, "description", None)
        self._file_path = file_path

        # Stream config
        stream_fmt = getattr(handler_cls, "stream_format", None)
        if stream_fmt is not None:
            self._stream_format = StreamFormat(stream_fmt)
        stream_fld = getattr(handler_cls, "stream_field", None)
        if stream_fld is not None:
            self._stream_field = stream_fld

        # Extract parameters from Pydantic Input model
        input_type = handler_cls._get_input_type()
        self._parameters = []
        for field_name, field_info in input_type.model_fields.items():
            annotation = field_info.annotation
            param_type = _ANNOTATION_MAP.get(annotation, "str")  # type: ignore[arg-type]
            # Also try the __name__ attribute for type objects
            if annotation not in _ANNOTATION_MAP and hasattr(annotation, "__name__"):
                param_type = _ANNOTATION_MAP.get(annotation.__name__, "str")  # type: ignore[union-attr]

            default_val: str | None = None
            if not field_info.is_required() and field_info.default is not None:
                default_val = str(field_info.default)

            self._parameters.append(
                ParameterDefinition(
                    name=field_name,
                    description=field_info.description or "",
                    param_type=param_type,
                    required=field_info.is_required(),
                    default=default_val,
                )
            )

    def build(self) -> ToolDefinition:
        if not self._name:
            raise ValueError("ToolDefinition requires a name")
        if not self._description:
            raise ValueError("ToolDefinition requires a description")
        if not self._file_path:
            raise ValueError("ToolDefinition requires a file_path")

        param_names = {p.name for p in self._parameters}
        if self._stream_field and self._stream_field not in param_names:
            raise ValueError(
                f"stream_field {self._stream_field!r} does not match "
                f"any parameter name: {param_names}"
            )

        return ToolDefinition(
            name=self._name,
            description=self._description,
            file_path=self._file_path,
            parameters=tuple(self._parameters),
            stream_format=self._stream_format,
            stream_field=self._stream_field,
        )
