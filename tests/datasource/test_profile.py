"""profile_datasource — structure enumeration + convention inference.

Drives the MCP Drive adapter through a MOCK and asserts the inferred
profile + the prompt-ready summary. Deterministic / offline.
"""

from __future__ import annotations

from open_agent_compiler.datasource.adapter import MCPDatasourceAdapter, ResourceBindingAdapter
from open_agent_compiler.datasource.profile import DatasourceProfile, profile_datasource
from open_agent_compiler.model.core.access_profile import ResourceBinding
from open_agent_compiler.model.core.context_blocks import ContextBlock

from tests.datasource.conftest import MockDBEnumerator, MockDriveEnumerator


def _drive_profile() -> DatasourceProfile:
    adapter = MCPDatasourceAdapter(
        name="client_drive", kind="gdrive",
        mcp_server_name="gdrive_mcp", enumerator=MockDriveEnumerator(),
    )
    return profile_datasource(adapter)


def test_profile_basic_counts() -> None:
    p = _drive_profile()
    assert p.datasource_name == "client_drive"
    assert p.kind == "gdrive"
    assert p.container_count == 5
    assert p.leaf_count == 5
    assert p.truncated is False


def test_profile_top_level_groups() -> None:
    p = _drive_profile()
    assert set(p.top_level_groups) == {"Clients", "Templates"}


def test_profile_max_depth() -> None:
    p = _drive_profile()
    # /Clients/acme/invoices/<file> = depth 4
    assert p.max_depth == 4


def test_profile_file_types() -> None:
    p = _drive_profile()
    assert p.file_types.get("pdf") == 3
    assert p.file_types.get("docx") == 2
    # pdf is the most common -> first key
    assert next(iter(p.file_types)) == "pdf"


def test_profile_naming_convention_detects_dated_prefix() -> None:
    p = _drive_profile()
    # 3 dated invoices dominate the 5 leaves (>50%).
    assert p.naming_convention == "dated_prefix"
    assert p.naming_distribution.get("dated_prefix") == 3


def test_profile_relevant_locations_points_at_invoices() -> None:
    p = _drive_profile()
    # The invoices folder holds the most leaves.
    assert p.relevant_locations[0] == "/Clients/acme/invoices"


def test_profile_sample_paths_present() -> None:
    p = _drive_profile()
    assert len(p.sample_paths) == 5
    assert all(path.startswith("/") for path in p.sample_paths)


def test_profile_summary_is_prompt_ready() -> None:
    p = _drive_profile()
    s = p.summary
    assert "client_drive" in s
    assert "Clients" in s and "Templates" in s
    assert "pdf" in s
    assert "/Clients/acme/invoices" in s
    assert "search" in s.lower()


def test_profile_context_block_seam() -> None:
    p = _drive_profile()
    block = p.context_block()
    assert isinstance(block, ContextBlock)
    assert block.name == "datasource:client_drive"
    assert block.volatility == "stable"
    assert block.render() == p.summary


def test_profile_is_deterministic() -> None:
    assert _drive_profile() == _drive_profile()


def test_profile_non_mcp_db_source() -> None:
    adapter = ResourceBindingAdapter(
        name="goal_db", kind="postgres", binding_name="goal_db",
        binding=ResourceBinding(kind="postgres"),
        enumerator=MockDBEnumerator(), root="public",
    )
    p = profile_datasource(adapter)
    assert p.kind == "postgres"
    assert p.leaf_count == 3
    assert p.file_types.get("table") == 3
    assert "table" in p.summary
