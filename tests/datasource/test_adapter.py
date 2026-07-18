"""DatasourceAdapter interface + concrete MCP / ResourceBinding shapes.

All IO is mocked (canned Drive / DB structures). No live MCP / network.
"""

from __future__ import annotations

import pytest

from open_agent_compiler.datasource.adapter import (
    DatasourceAdapter,
    DatasourceItem,
    DatasourceStructure,
    MCPDatasourceAdapter,
    MCPEnumerator,
    ResourceBindingAdapter,
    ResourceBindingEnumerator,
)
from open_agent_compiler.model.core.access_profile import ResourceBinding

from tests.datasource.conftest import (
    MockDBEnumerator,
    MockDriveEnumerator,
    canned_drive_structure,
)


def test_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        DatasourceAdapter(name="x")  # type: ignore[abstract]


def test_item_path_must_be_non_empty() -> None:
    with pytest.raises(ValueError):
        DatasourceItem(path="   ", name="x")


def test_structure_containers_and_leaves_split() -> None:
    s = canned_drive_structure()
    assert len(s.containers()) == 5
    assert len(s.leaves()) == 5
    assert all(i.is_container for i in s.containers())
    assert all(not i.is_container for i in s.leaves())


# ---- MCP adapter (Drive reference) ---------------------------------


def test_mcp_adapter_requires_server_name() -> None:
    with pytest.raises(ValueError):
        MCPDatasourceAdapter(
            name="drive", mcp_server_name="  ",
            enumerator=MockDriveEnumerator(),
        )


def test_mcp_adapter_satisfies_protocol() -> None:
    enum = MockDriveEnumerator()
    assert isinstance(enum, MCPEnumerator)


def test_mcp_adapter_enumerate_and_sample() -> None:
    enum = MockDriveEnumerator()
    adapter = MCPDatasourceAdapter(
        name="client_drive", kind="gdrive",
        mcp_server_name="gdrive_mcp", enumerator=enum,
    )
    assert isinstance(adapter, DatasourceAdapter)
    structure = adapter.enumerate_structure()
    assert isinstance(structure, DatasourceStructure)
    assert len(structure.items) == 10
    sample = adapter.sample(3)
    assert len(sample) == 3
    # connect was auto-called; enumerate hit the mock once.
    assert enum.enumerate_calls == 1
    assert enum.sample_calls == 1


def test_mcp_adapter_connect_is_idempotent() -> None:
    adapter = MCPDatasourceAdapter(
        name="d", mcp_server_name="s", enumerator=MockDriveEnumerator(),
    )
    adapter.connect()
    adapter.connect()
    # no exception; enumerate still works
    assert adapter.enumerate_structure().items


def test_mcp_adapter_sample_negative_n_raises() -> None:
    adapter = MCPDatasourceAdapter(
        name="d", mcp_server_name="s", enumerator=MockDriveEnumerator(),
    )
    with pytest.raises(ValueError):
        adapter.sample(-1)


# ---- ResourceBinding adapter (non-MCP / DB) ------------------------


def test_resource_binding_adapter_requires_binding_name() -> None:
    with pytest.raises(ValueError):
        ResourceBindingAdapter(
            name="db", binding_name="",
            binding=ResourceBinding(kind="postgres"),
            enumerator=MockDBEnumerator(),
        )


def test_resource_binding_adapter_enumerate_and_sample() -> None:
    enum = MockDBEnumerator()
    assert isinstance(enum, ResourceBindingEnumerator)
    adapter = ResourceBindingAdapter(
        name="goal_db", kind="postgres", binding_name="goal_db",
        binding=ResourceBinding(kind="postgres", config={"dsn": "x"}),
        enumerator=enum, root="public",
    )
    structure = adapter.enumerate_structure()
    assert structure.root == "public"
    assert len(structure.leaves()) == 3
    assert adapter.sample(2) == structure.leaves()[:2]
