"""ClientCapabilityBundle + merge_capabilities — Phase B capability merge.

Pure data + pure functions: no IO, no provider calls. Exercises the
opencode.json mcp assembly, the per-agent allow-list assembly, every
collision/precedence policy, the datasource extension seam, and the
empty-client (builtin-only) == today's-behavior invariant.
"""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.capability_bundle import (
    ClientCapabilityBundle,
    ClientDatasource,
    ClientMCPServer,
    MergedCapabilitySurface,
    merge_capabilities,
)


def _server(name="client_search", tools=("search",), **kw) -> ClientMCPServer:
    kw.setdefault("transport", "local")
    kw.setdefault("command", ("npx", "-y", name))
    return ClientMCPServer(name=name, tools=tools, **kw)


# ---- model validation ----------------------------------------------


def test_remote_server_requires_url() -> None:
    with pytest.raises(ValueError):
        ClientMCPServer(name="x", transport="remote")


def test_local_server_requires_command() -> None:
    with pytest.raises(ValueError):
        ClientMCPServer(name="x", transport="local")


def test_local_server_to_opencode_config() -> None:
    s = ClientMCPServer(
        name="drive", transport="local",
        command=("node", "drive.js"),
        environment={"TOKEN": "{env:DRIVE_TOKEN}"},
    )
    cfg = s.to_opencode_config()
    assert cfg == {
        "type": "local",
        "command": ["node", "drive.js"],
        "enabled": True,
        "environment": {"TOKEN": "{env:DRIVE_TOKEN}"},
    }


def test_remote_server_to_opencode_config() -> None:
    s = ClientMCPServer(name="api", transport="remote", url="https://x/mcp")
    assert s.to_opencode_config() == {
        "type": "remote", "url": "https://x/mcp", "enabled": True,
    }


# ---- empty client == today's behavior ------------------------------


def test_empty_client_is_builtin_only() -> None:
    bundle = ClientCapabilityBundle(builtin_tools=("read", "write", "bash"))
    surface = merge_capabilities(bundle)
    assert surface.allow_list == ("read", "write", "bash")
    assert surface.mcp_config == {}
    assert surface.aliases == {}
    assert surface.dropped == {}
    assert surface.opencode_json_fragment() == {"mcp": {}}


# ---- mcp.json assembly ---------------------------------------------


def test_mcp_section_assembles_every_server() -> None:
    bundle = ClientCapabilityBundle(
        builtin_tools=("read",),
        mcp_servers=(
            _server("client_search", ("search",)),
            ClientMCPServer(
                name="client_api", transport="remote", url="https://x/mcp",
                tools=("lookup",),
            ),
        ),
    )
    surface = merge_capabilities(bundle)
    assert set(surface.mcp_config) == {"client_search", "client_api"}
    assert surface.mcp_config["client_api"]["type"] == "remote"
    assert surface.mcp_config["client_search"]["type"] == "local"
    # Fragment is mergeable straight into opencode.json.
    assert surface.opencode_json_fragment()["mcp"] is not surface.mcp_config


# ---- allow-list assembly -------------------------------------------


def test_allow_list_unions_builtin_and_client_tools() -> None:
    bundle = ClientCapabilityBundle(
        builtin_tools=("read", "write"),
        mcp_servers=(_server("s", ("search", "fetch")),),
    )
    surface = merge_capabilities(bundle)
    assert surface.allow_list == ("read", "write", "search", "fetch")


def test_disabled_server_tools_excluded_from_allow_list() -> None:
    bundle = ClientCapabilityBundle(
        builtin_tools=("read",),
        mcp_servers=(_server("s", ("search",), enabled=False),),
    )
    surface = merge_capabilities(bundle)
    # Server still wired into mcp_config, but its tools aren't allow-listed.
    assert "search" not in surface.allow_list
    assert surface.allow_list == ("read",)
    assert "s" in surface.mcp_config


def test_allow_list_deduplicates() -> None:
    bundle = ClientCapabilityBundle(
        builtin_tools=("read",),
        mcp_servers=(
            _server("a", ("search",)),
            _server("b", ("search",)),  # same tool name on two servers
        ),
    )
    surface = merge_capabilities(bundle)
    assert surface.allow_list.count("search") == 1


# ---- collision / precedence policies -------------------------------


def _collision_bundle() -> ClientCapabilityBundle:
    return ClientCapabilityBundle(
        builtin_tools=("read", "search"),  # built-in 'search'
        mcp_servers=(_server("s", ("search",)),),  # client 'search' too
    )


def test_collision_namespace_client_keeps_both() -> None:
    surface = merge_capabilities(_collision_bundle(), policy="namespace_client")
    assert "search" in surface.allow_list  # built-in keeps bare name
    assert "client_search" in surface.allow_list  # client namespaced
    assert surface.aliases == {"search": "client_search"}
    assert surface.dropped == {}


def test_collision_custom_prefix() -> None:
    surface = merge_capabilities(
        _collision_bundle(), policy="namespace_client",
        namespace_prefix="acme__",
    )
    assert "acme__search" in surface.allow_list
    assert surface.aliases == {"search": "acme__search"}


def test_collision_client_overrides() -> None:
    surface = merge_capabilities(_collision_bundle(), policy="client_overrides")
    # bare name kept (now backed by client), no namespaced alias added.
    assert "search" in surface.allow_list
    assert "client_search" not in surface.allow_list
    assert "search" in surface.dropped  # records the shadow


def test_collision_builtin_wins() -> None:
    surface = merge_capabilities(_collision_bundle(), policy="builtin_wins")
    assert "search" in surface.allow_list
    assert "client_search" not in surface.allow_list
    assert surface.dropped["search"].startswith("client tool dropped")


def test_collision_error_raises() -> None:
    with pytest.raises(ValueError, match="collision"):
        merge_capabilities(_collision_bundle(), policy="error")


def test_no_collision_when_names_distinct() -> None:
    bundle = ClientCapabilityBundle(
        builtin_tools=("read",), mcp_servers=(_server("s", ("search",)),),
    )
    surface = merge_capabilities(bundle, policy="error")  # would raise if hit
    assert surface.aliases == {} and surface.dropped == {}


# ---- datasource extension seam (Phase C hand-off) -------------------


def test_datasource_derived_tools_flow_into_allow_list() -> None:
    bundle = ClientCapabilityBundle(
        builtin_tools=("read",),
        datasources=(
            ClientDatasource(
                name="client_drive", kind="gdrive",
                mcp_server_name="drive_mcp",
                derived_tools=("drive_query", "drive_rag"),
            ),
        ),
    )
    surface = merge_capabilities(bundle)
    assert "drive_query" in surface.allow_list
    assert "drive_rag" in surface.allow_list


def test_datasource_tool_names_collected_and_deduped() -> None:
    bundle = ClientCapabilityBundle(
        datasources=(
            ClientDatasource(name="a", derived_tools=("q", "r")),
            ClientDatasource(name="b", derived_tools=("r", "s")),
        ),
    )
    assert bundle.datasource_tool_names() == ("q", "r", "s")


def test_datasource_seam_empty_by_default() -> None:
    """A datasource with no adapter yet (Phase C) contributes no tools."""
    bundle = ClientCapabilityBundle(
        builtin_tools=("read",),
        datasources=(ClientDatasource(name="client_drive", kind="gdrive"),),
    )
    surface = merge_capabilities(bundle)
    assert surface.allow_list == ("read",)


def test_datasource_collides_with_builtin_under_policy() -> None:
    bundle = ClientCapabilityBundle(
        builtin_tools=("read",),
        datasources=(
            ClientDatasource(name="ds", derived_tools=("read",)),
        ),
    )
    surface = merge_capabilities(bundle, policy="namespace_client")
    assert surface.aliases == {"read": "client_read"}


def test_client_tool_names_union_mcp_and_datasource() -> None:
    bundle = ClientCapabilityBundle(
        mcp_servers=(_server("s", ("search",)),),
        datasources=(ClientDatasource(name="ds", derived_tools=("q",)),),
    )
    assert set(bundle.client_tool_names()) == {"search", "q"}


# ---- frozen / typing sanity ----------------------------------------


def test_surface_is_frozen() -> None:
    surface = merge_capabilities(ClientCapabilityBundle(builtin_tools=("r",)))
    assert isinstance(surface, MergedCapabilitySurface)
    with pytest.raises(Exception):
        surface.allow_list = ()  # type: ignore[misc]
