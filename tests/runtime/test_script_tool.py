"""ScriptTool runtime — type introspection and input/output schema generation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_agent_compiler.runtime import ScriptTool


class _In(BaseModel):
    name: str = Field(description="who to greet")
    times: int = Field(default=1, description="how many greetings")


class _Out(BaseModel):
    greetings: list[str]


class _Greeter(ScriptTool[_In, _Out]):
    name = "greeter"
    description = "Greet someone N times."

    def execute(self, input: _In) -> _Out:
        return _Out(greetings=[f"hi {input.name}"] * input.times)


def test_input_type_resolved_from_generic_param() -> None:
    assert _Greeter._get_input_type() is _In
    assert _Greeter._get_output_type() is _Out


def test_input_schema_lists_fields_with_required_flag() -> None:
    schema = _Greeter.get_input_schema()
    by_name = {f["name"]: f for f in schema}
    assert by_name["name"]["required"] is True
    assert by_name["times"]["required"] is False
    assert by_name["name"]["description"] == "who to greet"


def test_execute_runs_business_logic() -> None:
    out = _Greeter().execute(_In(name="ada", times=3))
    assert out.greetings == ["hi ada", "hi ada", "hi ada"]


# ---- Phase 15: resources kwarg on execute -----------------------------


import json

from open_agent_compiler.runtime import RESOURCES_ENV, ResourceHandle


class _DBOut(BaseModel):
    note: str


class _ResourceAwareTool(ScriptTool[_In, _DBOut]):
    """Tool that opts into the (input, resources) signature."""

    name = "rt"
    description = "Resource-aware tool used in tests."

    def execute(self, input: _In, resources=None) -> _DBOut:
        if not resources:
            return _DBOut(note="no resources")
        handle = resources.get("notes_db")
        if handle is None:
            return _DBOut(note="no notes_db binding")
        return _DBOut(note=f"kind={handle.kind} path={handle.config.get('path')}")


def test_resource_handle_carries_binding_fields() -> None:
    h = ResourceHandle(
        name="notes_db", kind="sqlite", config={"path": ":memory:"},
    )
    assert h.kind == "sqlite"
    assert h.config["path"] == ":memory:"
    assert h.mock_only is False


def test_resource_handle_sqlite_connect_returns_sqlite3_connection() -> None:
    h = ResourceHandle(
        name="d", kind="sqlite", config={"path": ":memory:"},
    )
    conn = h.sqlite_connect()
    try:
        conn.execute("create table t(x int)")
        conn.execute("insert into t values (1)")
        assert conn.execute("select count(*) from t").fetchone() == (1,)
    finally:
        conn.close()


def test_resource_handle_sqlite_connect_refuses_wrong_kind() -> None:
    import pytest
    h = ResourceHandle(name="d", kind="postgres", config={})
    with pytest.raises(ValueError, match="not 'sqlite'"):
        h.sqlite_connect()


def test_resource_handle_mock_only_refuses_connect() -> None:
    import pytest
    h = ResourceHandle(
        name="d", kind="sqlite", config={"path": ":memory:"},
        mock_only=True,
    )
    with pytest.raises(RuntimeError, match="mock_only"):
        h.sqlite_connect()


def test_invoke_execute_passes_resources_when_signature_accepts_them(
    monkeypatch,
) -> None:
    """Tool with the (input, resources) signature receives a handle dict."""
    monkeypatch.setenv(
        RESOURCES_ENV,
        json.dumps({
            "notes_db": {"kind": "sqlite", "config": {"path": "/tmp/x.db"}},
        }),
    )
    out = _ResourceAwareTool()._invoke_execute(_In(name="ada"))
    assert out.note == "kind=sqlite path=/tmp/x.db"


def test_invoke_execute_no_resources_for_legacy_signature(
    monkeypatch,
) -> None:
    """Legacy tools with (input) signature still work even when env is set."""
    monkeypatch.setenv(
        RESOURCES_ENV,
        json.dumps({"d": {"kind": "sqlite", "config": {}}}),
    )
    # _Greeter.execute is the old (self, input) shape — no breakage.
    out = _Greeter()._invoke_execute(_In(name="ada", times=2))
    assert out.greetings == ["hi ada", "hi ada"]


def test_invoke_execute_empty_resources_when_env_unset(
    monkeypatch,
) -> None:
    monkeypatch.delenv(RESOURCES_ENV, raising=False)
    out = _ResourceAwareTool()._invoke_execute(_In(name="ada"))
    assert out.note == "no resources"


def test_invoke_execute_handles_kwargs_signature(monkeypatch) -> None:
    """A tool using **kwargs also opts into resources."""

    class _KwargsTool(ScriptTool[_In, _DBOut]):
        name = "k"
        description = "uses **kwargs"
        def execute(self, input, **kwargs) -> _DBOut:
            return _DBOut(note=f"has-resources={bool(kwargs.get('resources'))}")

    monkeypatch.setenv(
        RESOURCES_ENV,
        json.dumps({"d": {"kind": "sqlite", "config": {}}}),
    )
    out = _KwargsTool()._invoke_execute(_In(name="x"))
    assert out.note == "has-resources=True"
