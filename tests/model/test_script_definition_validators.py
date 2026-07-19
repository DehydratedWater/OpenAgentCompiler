"""ScriptDefinition validators: type inference, mismatch, content presence."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from open_agent_compiler.model.core.tools_model import ScriptDefinition


def test_infers_type_from_suffix_when_none():
    d = ScriptDefinition(
        target_file_path=Path("scripts/weather.py"),
        source_file_path=None,
        source_file_type=None,
        script_contents="print('hi')\n",
    )
    assert d.source_file_type == "python"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("t.py", "python"), ("t.js", "javascript"), ("t.mjs", "javascript"),
     ("t.ts", "typescript"), ("t.tsx", "typescript")],
)
def test_suffix_map(name, expected):
    d = ScriptDefinition(
        target_file_path=Path(name),
        source_file_path=None,
        source_file_type=None,
        script_contents="x",
    )
    assert d.source_file_type == expected


def test_unknown_suffix_stays_none():
    d = ScriptDefinition(
        target_file_path=Path("scripts/query.sql"),
        source_file_path=None,
        source_file_type=None,
        script_contents="select 1;",
    )
    assert d.source_file_type is None


def test_declared_type_mismatching_suffix_rejected():
    with pytest.raises(ValidationError, match="does not match"):
        ScriptDefinition(
            target_file_path=Path("scripts/weather.ts"),
            source_file_path=None,
            source_file_type="python",
            script_contents="x",
        )


def test_no_content_and_no_source_rejected():
    with pytest.raises(ValidationError, match="carries no content"):
        ScriptDefinition(
            target_file_path=Path("scripts/weather.py"),
            source_file_path=None,
            source_file_type="python",
            script_contents=None,
        )


def test_absolute_missing_source_rejected(tmp_path):
    with pytest.raises(ValidationError, match="does not exist"):
        ScriptDefinition(
            target_file_path=Path("scripts/weather.py"),
            source_file_path=tmp_path / "nope.py",
            source_file_type="python",
            script_contents=None,
        )


def test_existing_source_accepted(tmp_path):
    src = tmp_path / "weather.py"
    src.write_text("print('hi')\n")
    d = ScriptDefinition(
        target_file_path=Path("scripts/weather.py"),
        source_file_path=src,
        source_file_type=None,
        script_contents=None,
    )
    assert d.source_file_type == "python"


def test_relative_source_not_fs_checked():
    # Relative sources resolve at compile time against the project root;
    # construction must not assume the cwd.
    d = ScriptDefinition(
        target_file_path=Path("scripts/weather.py"),
        source_file_path=Path("scripts/weather.py"),
        source_file_type="python",
        script_contents=None,
    )
    assert d.script_contents is None
