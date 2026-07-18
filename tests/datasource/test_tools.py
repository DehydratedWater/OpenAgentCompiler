"""Derived datasource tools + the merge_capabilities flow.

Asserts the declarative tool specs, that apply_profile_to_datasource
populates ClientDatasource.derived_tools, and that those names flow
through merge_capabilities into the per-client allow-list.
"""

from __future__ import annotations

from open_agent_compiler.datasource.adapter import MCPDatasourceAdapter
from open_agent_compiler.datasource.profile import profile_datasource
from open_agent_compiler.datasource.tools import (
    ToolInputSchema,
    apply_profile_to_datasource,
    derive_datasource_tools,
)
from open_agent_compiler.model.core.capability_bundle import (
    ClientCapabilityBundle,
    ClientDatasource,
    ClientMCPServer,
    merge_capabilities,
)

from tests.datasource.conftest import MockDriveEnumerator


def _profile():
    adapter = MCPDatasourceAdapter(
        name="client_drive", kind="gdrive",
        mcp_server_name="gdrive_mcp", enumerator=MockDriveEnumerator(),
    )
    return profile_datasource(adapter)


def test_input_schema_to_json_schema() -> None:
    schema = ToolInputSchema(
        properties={"query": "string"}, required=("query",),
        descriptions={"query": "the query"},
    )
    js = schema.to_json_schema()
    assert js["type"] == "object"
    assert js["properties"]["query"] == {"type": "string", "description": "the query"}
    assert js["required"] == ["query"]


def test_derive_tools_shapes() -> None:
    specs = derive_datasource_tools(_profile(), mcp_server_name="gdrive_mcp")
    assert len(specs) == 2
    search, read = specs
    assert search.name == "search_client_drive"
    assert read.name == "read_client_drive_by_path"
    assert search.kind == "search"
    assert read.kind == "read"
    # MCP realization path recorded for Phase E.
    assert search.mcp_server_name == "gdrive_mcp"
    # navigation hints baked into the description
    assert "/Clients/acme/invoices" in search.description
    assert "dated_prefix" in search.description
    assert "query" in search.input_schema.properties
    assert "path" in read.input_schema.properties


def test_derive_tools_slugifies_name() -> None:
    p = _profile().model_copy(update={"datasource_name": "Client Drive #1"})
    specs = derive_datasource_tools(p)
    assert specs[0].name == "search_client_drive_1"


def test_apply_profile_populates_derived_tools() -> None:
    ds = ClientDatasource(
        name="client_drive", kind="gdrive", mcp_server_name="gdrive_mcp",
    )
    assert ds.derived_tools == ()
    updated = apply_profile_to_datasource(ds, _profile())
    assert updated.derived_tools == (
        "search_client_drive", "read_client_drive_by_path",
    )
    # immutable: original untouched
    assert ds.derived_tools == ()


def test_derived_tools_flow_through_merge_capabilities() -> None:
    ds = apply_profile_to_datasource(
        ClientDatasource(
            name="client_drive", kind="gdrive", mcp_server_name="gdrive_mcp",
        ),
        _profile(),
    )
    server = ClientMCPServer(
        name="gdrive_mcp", transport="local",
        command=("node", "drive_mcp.js"),
    )
    bundle = ClientCapabilityBundle(
        client_id="acme",
        builtin_tools=("read", "write"),
        mcp_servers=(server,),
        datasources=(ds,),
    )
    # datasource_tool_names picks up the derived tools
    assert bundle.datasource_tool_names() == (
        "search_client_drive", "read_client_drive_by_path",
    )
    surface = merge_capabilities(bundle)
    # The derived datasource tools land in the merged per-agent allow-list.
    assert "search_client_drive" in surface.allow_list
    assert "read_client_drive_by_path" in surface.allow_list
    # built-ins still present (backward-compatible)
    assert "read" in surface.allow_list and "write" in surface.allow_list
    # MCP server wired into opencode.json
    assert "gdrive_mcp" in surface.mcp_config


def test_apply_profile_non_mcp_records_binding_name() -> None:
    ds = ClientDatasource(
        name="goal_db", kind="postgres", binding_name="goal_db",
    )
    p = _profile().model_copy(update={"datasource_name": "goal_db", "kind": "postgres"})
    updated = apply_profile_to_datasource(ds, p)
    assert updated.derived_tools == ("search_goal_db", "read_goal_db_by_path")
    specs = derive_datasource_tools(p, binding_name="goal_db")
    assert specs[0].binding_name == "goal_db"
    assert specs[0].mcp_server_name is None
