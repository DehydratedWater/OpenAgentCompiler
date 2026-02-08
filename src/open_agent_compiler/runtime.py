# DO NOT add `from __future__ import annotations` here.
# Pydantic v2 introspection and `__orig_bases__` generic extraction
# require concrete types at class definition time.
"""ScriptTool — runtime base class for script-based tools."""

import argparse
import json
import sys
import typing
from abc import ABC, abstractmethod
from typing import ClassVar, Generic, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

from open_agent_compiler._types import StreamFormat

TInput = TypeVar("TInput", bound=BaseModel)
TOutput = TypeVar("TOutput", bound=BaseModel)

# Mapping from Python annotation names to argparse-compatible types
_TYPE_MAP: dict[str, type[str] | type[int] | type[float]] = {
    "str": str,
    "int": int,
    "float": float,
}


class ScriptTool(ABC, Generic[TInput, TOutput]):
    """Base class for script-based tools.

    Subclasses define Pydantic Input/Output models as type parameters and
    implement ``execute()``.  The ``run()`` classmethod provides a CLI entry
    point that parses arguments, validates with Pydantic, and prints JSON.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    stream_format: ClassVar[StreamFormat | None] = None
    stream_field: ClassVar[str | None] = None

    @abstractmethod
    def execute(self, input: TInput) -> TOutput:
        """Run the tool logic — implement in subclass."""
        ...

    @classmethod
    def _get_input_type(cls) -> type[BaseModel]:
        """Extract TInput from ``cls.__orig_bases__``."""
        for base in getattr(cls, "__orig_bases__", ()):
            args = typing.get_args(base)
            if args and len(args) >= 1:
                candidate = args[0]
                if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                    return candidate
        raise TypeError(
            f"{cls.__name__} must parameterise ScriptTool[Input, Output] "
            "with concrete Pydantic models"
        )

    @classmethod
    def _get_output_type(cls) -> type[BaseModel]:
        """Extract TOutput from ``cls.__orig_bases__``."""
        for base in getattr(cls, "__orig_bases__", ()):
            args = typing.get_args(base)
            if args and len(args) >= 2:
                candidate = args[1]
                if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                    return candidate
        raise TypeError(
            f"{cls.__name__} must parameterise ScriptTool[Input, Output] "
            "with concrete Pydantic models"
        )

    @classmethod
    def _build_argparse(cls) -> argparse.ArgumentParser:
        """Generate an ArgumentParser from the Input model's fields."""
        input_type = cls._get_input_type()
        parser = argparse.ArgumentParser(
            prog=cls.name,
            description=cls.description,
        )
        parser.add_argument(
            "--json",
            dest="json_mode",
            action="store_true",
            default=False,
            help="Read full JSON input from stdin",
        )

        for field_name, field_info in input_type.model_fields.items():
            annotation = field_info.annotation
            type_name = getattr(annotation, "__name__", str(annotation))

            # Skip complex types — must use --json mode
            if type_name not in _TYPE_MAP and type_name != "bool":
                continue

            if type_name == "bool":
                parser.add_argument(
                    f"--{field_name}",
                    action=argparse.BooleanOptionalAction,
                    default=(
                        field_info.default if field_info.default is not None else None
                    ),
                    help=field_info.description or "",
                )
            else:
                kwargs: dict[str, object] = {
                    "type": _TYPE_MAP[type_name],
                    "help": field_info.description or "",
                }
                if not field_info.is_required():
                    kwargs["default"] = field_info.default
                # Never mark argparse args as required — Pydantic validates instead.
                # This allows --json and stdin streaming to work without all CLI args.
                kwargs["required"] = False
                parser.add_argument(f"--{field_name}", **kwargs)  # type: ignore[arg-type]

        return parser

    @classmethod
    def run(cls) -> None:
        """Entry point: parse args/stdin, validate, execute, JSON output."""
        load_dotenv()

        input_type = cls._get_input_type()
        parser = cls._build_argparse()
        args = parser.parse_args()

        stdin_data: str | None = None
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.read()

        if args.json_mode and stdin_data:
            # Full JSON via stdin
            data = json.loads(stdin_data)
            validated = input_type.model_validate(data)
        elif stdin_data and cls.stream_field:
            # One field via stdin, rest from CLI args
            cli_data = {
                k: v
                for k, v in vars(args).items()
                if k != "json_mode" and v is not None
            }
            cli_data[cls.stream_field] = stdin_data.rstrip("\n")
            validated = input_type.model_validate(cli_data)
        else:
            # All from CLI args
            cli_data = {
                k: v
                for k, v in vars(args).items()
                if k != "json_mode" and v is not None
            }
            validated = input_type.model_validate(cli_data)

        instance = cls()
        result = instance.execute(validated)  # type: ignore[arg-type]
        print(json.dumps(result.model_dump(), default=str))
