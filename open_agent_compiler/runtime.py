"""ScriptTool - runtime base class for script-based tools."""

import argparse
import importlib
import inspect
import json
import os
import sys
from abc import ABC, abstractmethod
from enum import Enum
from types import UnionType
from typing import Any, ClassVar, Generic, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel

TInput = TypeVar("TInput", bound=BaseModel)
TOutput = TypeVar("TOutput", bound=BaseModel)

_TYPE_MAP = {"str": str, "int": int, "float": float}


def _scalar_type_name(annotation: Any) -> str:
    """Resolve a field annotation to a scalar type name for CLI generation.

    Unwraps Optional / `T | None` (and other 1-non-None unions) to the inner
    scalar so that fields typed `int | None`, `float | None`, etc. still get a
    CLI flag (previously they were silently dropped). Returns the bare type's
    __name__, or str(annotation) when it isn't a recognizable scalar.
    """
    if get_origin(annotation) in (Union, UnionType):
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        if len(non_none) == 1:
            annotation = non_none[0]
    return getattr(annotation, "__name__", str(annotation))

# Env var the compiler sets when a test variant is invoked. When set, the
# script returns its mock response instead of calling execute().
MOCK_ENV = "OAC_MOCK_RESPONSE"

# Env var carrying the JSON-serialised effective ResourceBinding map for
# the active AccessProfile, filtered to just the resources this tool
# requires. The runtime reads it and constructs ResourceHandle objects
# the tool's execute() can use. Empty / unset → no handles available.
RESOURCES_ENV = "OAC_RESOURCES_JSON"


class ResourceHandle:
    """Runtime view of one bound resource from an AccessProfile.

    Carries the binding's `kind` + opaque `config` dict from the
    compile-time AccessProfile, plus convenience helpers for the most
    common kinds. A tool's `execute(input, resources)` receives a
    `dict[str, ResourceHandle]` keyed by the symbolic resource name the
    tool declared in `requires_resources`.

    When `mock_only` is True the binding exists only to satisfy a
    MockProfile-covered test and connecting through it raises so a
    misconfigured test fails loudly rather than silently producing
    wrong data.
    """

    def __init__(
        self, name: str, kind: str, config: dict[str, Any],
        *, mock_only: bool = False,
    ) -> None:
        self.name = name
        self.kind = kind
        self.config = dict(config)
        self.mock_only = mock_only

    def sqlite_connect(self):
        """Return a sqlite3.Connection from this binding.

        Reads `config['path']` (defaults to ':memory:'). Raises when the
        binding's kind isn't 'sqlite' or when the binding is marked
        mock_only.
        """
        import sqlite3
        if self.mock_only:
            raise RuntimeError(
                f"resource {self.name!r} is mock_only — cannot connect"
            )
        if self.kind != "sqlite":
            raise ValueError(
                f"resource {self.name!r} is kind={self.kind!r}, not 'sqlite'"
            )
        path = self.config.get("path", ":memory:")
        return sqlite3.connect(path)

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return (
            f"ResourceHandle(name={self.name!r}, kind={self.kind!r},"
            f" mock_only={self.mock_only})"
        )


def _load_resources_from_env() -> dict[str, ResourceHandle]:
    """Parse `OAC_RESOURCES_JSON` into a dict of ResourceHandle.

    Expected JSON shape:
        {"<resource_name>": {"kind": "sqlite", "config": {...},
                              "mock_only": false}, ...}
    Empty / unset env var returns an empty dict (no handles available).
    """
    raw = os.environ.get(RESOURCES_ENV)
    if not raw:
        return {}
    payload = json.loads(raw)
    out: dict[str, ResourceHandle] = {}
    for name, binding in payload.items():
        out[name] = ResourceHandle(
            name=name,
            kind=binding["kind"],
            config=binding.get("config", {}),
            mock_only=binding.get("mock_only", False),
        )
    return out


class StreamFormat(str, Enum):
    """How a tool's output should be streamed to the caller's stdout.

    A presentation hint carried on the tool (v1-runtime parity): TEXT streams a
    single `stream_field` as plain text; JSON/XML serialise the whole output.
    The runtime treats it as advisory — tools that don't set it default to JSON.
    """

    TEXT = "text"
    JSON = "json"
    XML = "xml"


class ScriptTool(ABC, Generic[TInput, TOutput]):
    name: ClassVar[str]
    description: ClassVar[str]
    # Optional output-streaming hints (v1 parity). Default: serialise as JSON.
    stream_format: ClassVar[StreamFormat] = StreamFormat.JSON
    stream_field: ClassVar[str | None] = None

    @abstractmethod
    def execute(self, input: TInput) -> TOutput:
        """Run the tool against `input` and return a typed output.

        Two signature shapes are supported and the runtime detects
        which one a subclass declares:

            def execute(self, input: TInput) -> TOutput:
                # Self-contained tool with no external resources.

            def execute(
                self, input: TInput,
                resources: dict[str, ResourceHandle] | None = None,
            ) -> TOutput:
                # Tool that talks to a DB / API / MCP / FS / vLLM. The
                # framework passes a ResourceHandle for each name the
                # tool declared in `requires_resources`, populated from
                # the active AccessProfile's bindings.

        Subclasses with the 2-arg signature can call
        `resources['my_db'].sqlite_connect()` (or use the kind / config
        directly) and trust that the compile pipeline validated the
        binding before the script was ever invoked.
        """
        ...

    def mock_response(self, input: TInput) -> TOutput | None:
        """Override to provide a deterministic mock output.

        Returning None means "no mock available, fall through to whatever
        the runtime resolver dictates". The runtime CLI calls this first
        when --mock is passed or OAC_MOCK_RESPONSE is set.
        """
        return None

    @classmethod
    def _get_input_type(cls) -> type[BaseModel]:
        import typing
        for base in getattr(cls, "__orig_bases__", ()):
            args = typing.get_args(base)
            if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                return args[0]
        raise TypeError(f"{cls.__name__} must parameterise ScriptTool[Input, Output]")

    @classmethod
    def _get_output_type(cls) -> type[BaseModel]:
        import typing
        for base in getattr(cls, "__orig_bases__", ()):
            args = typing.get_args(base)
            if args and len(args) >= 2 and isinstance(args[1], type) and issubclass(args[1], BaseModel):
                return args[1]
        raise TypeError(f"{cls.__name__} must parameterise ScriptTool[Input, Output]")

    @classmethod
    def _build_argparse(cls) -> argparse.ArgumentParser:
        input_type = cls._get_input_type()
        parser = argparse.ArgumentParser(prog=cls.name, description=cls.description)
        parser.add_argument("--json", dest="json_mode", action="store_true", default=False)
        parser.add_argument(
            "--mock",
            dest="mock_spec",
            default=None,
            help=(
                "Use a mock response. Either a JSON literal, a path to a JSON file,"
                " or 'echo' to echo input. Overrides OAC_MOCK_RESPONSE."
            ),
        )
        parser.add_argument(
            "--mock-callable",
            dest="mock_callable",
            default=None,
            help="Import 'module:callable' and call it with the validated input.",
        )
        for field_name, field_info in input_type.model_fields.items():
            type_name = _scalar_type_name(field_info.annotation)
            if type_name not in _TYPE_MAP and type_name != "bool":
                continue
            if type_name == "bool":
                parser.add_argument(f"--{field_name}", action=argparse.BooleanOptionalAction,
                                    default=field_info.default)
            else:
                kwargs = {"type": _TYPE_MAP[type_name], "help": field_info.description or "", "required": False}
                if not field_info.is_required():
                    kwargs["default"] = field_info.default
                parser.add_argument(f"--{field_name}", **kwargs)
        return parser

    @classmethod
    def get_input_schema(cls) -> list[dict[str, str]]:
        """Return input field metadata for compiler template generation."""
        input_type = cls._get_input_type()
        fields = []
        for field_name, field_info in input_type.model_fields.items():
            type_name = _scalar_type_name(field_info.annotation)
            fields.append({
                "name": field_name,
                "type": type_name,
                "description": field_info.description or "",
                "required": field_info.is_required(),
            })
        return fields

    @classmethod
    def run(cls) -> None:
        input_type = cls._get_input_type()
        parser = cls._build_argparse()
        args = parser.parse_args()
        stdin_data = sys.stdin.read() if not sys.stdin.isatty() else None
        cli_kwargs = {
            k: v for k, v in vars(args).items()
            if k not in {"json_mode", "mock_spec", "mock_callable"} and v is not None
        }
        if args.json_mode and stdin_data:
            validated = input_type.model_validate(json.loads(stdin_data))
        else:
            validated = input_type.model_validate(cli_kwargs)

        mock_payload = cls._resolve_mock(args, validated)
        if mock_payload is not None:
            print(json.dumps(mock_payload, default=str))
            return

        instance = cls()
        result = instance._invoke_execute(validated)
        print(json.dumps(result.model_dump(), default=str))

    def _invoke_execute(self, validated: BaseModel):
        """Call `self.execute(input)` or `self.execute(input, resources)`.

        Existing tools whose execute() signature is `(self, input)` keep
        working unchanged — no resources are passed. Tools that opt in
        with `(self, input, resources)` (or `**kwargs`) receive the
        ResourceHandle map built from OAC_RESOURCES_JSON. This keeps
        Phase 15's new signature additive and backwards-compatible.
        """
        sig = inspect.signature(self.execute)
        if (
            "resources" in sig.parameters
            or any(
                p.kind is inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            )
        ):
            return self.execute(validated, resources=_load_resources_from_env())
        return self.execute(validated)

    @classmethod
    def _resolve_mock(
        cls, args: argparse.Namespace, validated: BaseModel
    ) -> dict | None:
        """Return a mock payload to emit, or None to fall through to execute().

        Resolution order: --mock-callable, --mock, OAC_MOCK_RESPONSE env var,
        the subclass's mock_response() override.
        """
        if args.mock_callable:
            spec = args.mock_callable
            if ":" not in spec:
                raise ValueError(
                    f"--mock-callable must be 'module:callable', got {spec!r}"
                )
            mod_name, attr = spec.rsplit(":", 1)
            fn = getattr(importlib.import_module(mod_name), attr)
            out = fn(validated)
            return out.model_dump() if isinstance(out, BaseModel) else dict(out)

        spec = args.mock_spec or os.environ.get(MOCK_ENV)
        if spec:
            if spec == "echo":
                return validated.model_dump()
            payload = json.loads(spec) if spec.lstrip().startswith(("{", "[")) else \
                json.loads(__import__("pathlib").Path(spec).read_text())
            return payload

        override = cls().mock_response(validated)
        if override is not None:
            return override.model_dump() if isinstance(override, BaseModel) else dict(override)
        return None
