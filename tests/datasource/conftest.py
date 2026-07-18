"""Shared mocks for Phase C datasource tests.

A canned Google Drive folder/file structure + mock enumerators. NO live
MCP / Drive / network — everything returns fixed in-memory data.
"""

from __future__ import annotations

from open_agent_compiler.datasource.adapter import (
    DatasourceItem,
    DatasourceStructure,
)
from open_agent_compiler.model.core.access_profile import ResourceBinding


def canned_drive_structure() -> DatasourceStructure:
    """A small but realistic client Google Drive layout.

    Two top-level groups (Clients, Templates), nested client folders,
    invoices + contracts (pdf/docx) with snake_case + dated-prefix names.
    """
    items = (
        DatasourceItem(path="/Clients", name="Clients", is_container=True, item_type="folder"),
        DatasourceItem(path="/Templates", name="Templates", is_container=True, item_type="folder"),
        DatasourceItem(path="/Clients/acme", name="acme", is_container=True, item_type="folder"),
        DatasourceItem(path="/Clients/acme/invoices", name="invoices", is_container=True, item_type="folder"),
        DatasourceItem(path="/Clients/acme/contracts", name="contracts", is_container=True, item_type="folder"),
        DatasourceItem(
            path="/Clients/acme/invoices/2026-01-15_invoice_001.pdf",
            name="2026-01-15_invoice_001.pdf", item_type="pdf",
            size=12000, mime="application/pdf",
        ),
        DatasourceItem(
            path="/Clients/acme/invoices/2026-02-10_invoice_002.pdf",
            name="2026-02-10_invoice_002.pdf", item_type="pdf",
            size=12500, mime="application/pdf",
        ),
        DatasourceItem(
            path="/Clients/acme/invoices/2026-03-05_invoice_003.pdf",
            name="2026-03-05_invoice_003.pdf", item_type="pdf",
            size=13000, mime="application/pdf",
        ),
        DatasourceItem(
            path="/Clients/acme/contracts/master_service_agreement.docx",
            name="master_service_agreement.docx", item_type="docx",
            size=40000,
        ),
        DatasourceItem(
            path="/Templates/invoice_template.docx",
            name="invoice_template.docx", item_type="docx", size=8000,
        ),
    )
    return DatasourceStructure(root="/", items=items, truncated=False)


class MockDriveEnumerator:
    """Mock MCPEnumerator returning the canned Drive structure/sample."""

    def __init__(self, structure: DatasourceStructure | None = None) -> None:
        self._structure = structure or canned_drive_structure()
        self.enumerate_calls = 0
        self.sample_calls = 0

    def enumerate(self, *, root: str) -> DatasourceStructure:
        self.enumerate_calls += 1
        return self._structure

    def sample(self, *, n: int) -> tuple[DatasourceItem, ...]:
        self.sample_calls += 1
        leaves = self._structure.leaves()
        return leaves[:n]


def canned_db_structure() -> DatasourceStructure:
    items = (
        DatasourceItem(path="public", name="public", is_container=True, item_type="schema"),
        DatasourceItem(path="public.customers", name="customers", item_type="table"),
        DatasourceItem(path="public.orders", name="orders", item_type="table"),
        DatasourceItem(path="public.order_items", name="order_items", item_type="table"),
    )
    return DatasourceStructure(root="public", items=items)


class MockDBEnumerator:
    """Mock ResourceBindingEnumerator for a non-MCP (DB) source."""

    def __init__(self, structure: DatasourceStructure | None = None) -> None:
        self._structure = structure or canned_db_structure()

    def enumerate(self, *, binding: ResourceBinding, root: str) -> DatasourceStructure:
        return self._structure

    def sample(self, *, binding: ResourceBinding, n: int) -> tuple[DatasourceItem, ...]:
        return self._structure.leaves()[:n]
