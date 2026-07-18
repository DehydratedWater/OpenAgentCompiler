"""CLI plumbing: parser construction, factory loading, top-level dispatch."""

from __future__ import annotations

import pytest

from open_agent_compiler.cli.main import _load_factory, build_parser, main


# A factory installed at module level so _load_factory can resolve it.
def _example_factory():  # pragma: no cover - resolved by string
    from open_agent_compiler import AgentRegistry

    return AgentRegistry()


def test_parser_lists_all_subcommands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    for cmd in ("compile", "info", "test"):
        assert cmd in help_text


def test_no_args_prints_help_and_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "compile" in out


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "oac" in out


def test_load_factory_rejects_missing_colon() -> None:
    with pytest.raises(ValueError, match="must be 'module:callable'"):
        _load_factory("no_colon_here")


def test_load_factory_rejects_missing_attr() -> None:
    with pytest.raises(ValueError, match="no attribute"):
        _load_factory(f"{__name__}:_nope_definitely_not_here")


def test_load_factory_resolves_valid_spec() -> None:
    factory = _load_factory(f"{__name__}:_example_factory")
    registry = factory()
    assert registry.list_agents() == []


def test_info_subcommand_lists_registry_contents(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["info", f"{__name__}:_example_factory"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Agents (0)" in out
    assert "Templates (0)" in out
    assert "Configs (0)" in out


def test_test_subcommand_requires_config_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`oac test` now requires --config (Phase 5.7 wired the real impl)."""
    with pytest.raises(SystemExit) as exc:
        main(["test", f"{__name__}:_example_factory"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--config" in err


def test_compile_parser_accepts_dialect_flag() -> None:
    from open_agent_compiler.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args([
        "compile", "agents:registry",
        "--config", "prod", "--target", "build", "--dialect", "pi",
    ])
    assert args.dialect == "pi"


def test_info_dialects_lists_registered_dialects(capsys) -> None:
    from open_agent_compiler.cli.commands import info as info_cmd

    ns = __import__("argparse").Namespace(factory=None, dialects=True)
    rc = info_cmd.handle(ns, load_factory=lambda s: None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "opencode" in out
    assert "pi" in out
    assert "claude" in out


def test_compile_script_resolves_factory_spec_from_cwd(tmp_path, monkeypatch) -> None:
    """`oac compile agents:registry` must work from a scaffolded project
    root without installing the project (python -m semantics)."""
    import sys

    pkg = tmp_path / "cwdagents"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "def factory():\n    return 'sentinel-registry'\n"
    )
    monkeypatch.chdir(tmp_path)
    from open_agent_compiler.compiler.script import CompileScript

    script = CompileScript(
        target=tmp_path / "build",
        factory_spec="cwdagents:factory",
        config="prod",
    )
    try:
        assert script.resolve_factory()() == "sentinel-registry"
    finally:
        sys.modules.pop("cwdagents", None)
        sys.path.remove(str(tmp_path))
