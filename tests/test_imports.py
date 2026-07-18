"""Smoke test — every module in open_agent_compiler/ must be importable.

This is the cheapest possible regression net for refactors. If a module
develops a syntax error or a circular import, this test fails before any
behavior test even gets a chance to run.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest


def _walk_modules(package_name: str) -> list[str]:
    package = importlib.import_module(package_name)
    paths = getattr(package, "__path__", None)
    if paths is None:
        return [package_name]
    names = [package_name]
    for _finder, mod_name, _is_pkg in pkgutil.walk_packages(paths, prefix=f"{package_name}."):
        names.append(mod_name)
    return names


MODULES = _walk_modules("open_agent_compiler")


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)
