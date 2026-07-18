"""`oac improve` CLI end-to-end."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_agent_compiler.cli.commands.improve import _load_evaluator, _parse_mutators
from open_agent_compiler.cli.main import main as cli_main
from open_agent_compiler.improvement.mutators import (
    IdentityMutator,
    PromptPrefixMutator,
    TemperatureMutator,
)
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry


def _factory():
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="x", name="orch", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="be polite",
    )
    agent_id = reg.register_agent(
        "orch", agent,
        ModelParameters(model_name="m", temperature=0.5),
    )
    reg.register_template(
        TemplateTree(
            name="t",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="t"),
    )
    return reg


def _evaluator_always_passes(version):  # pragma: no cover - used by spec
    return {"pass_rate": 1.0}


def _evaluator_prefix_wins(version):  # pragma: no cover - used by spec
    prompt = version.definition.get("system_prompt", "")
    return {"pass_rate": 1.0 if "CRITICAL:" in prompt else 0.5}


# ---- _parse_mutators --------------------------------------------------


def test_parse_mutators_identity() -> None:
    out = _parse_mutators("identity")
    assert len(out) == 1
    assert isinstance(out[0], IdentityMutator)


def test_parse_mutators_with_args() -> None:
    out = _parse_mutators("prompt-prefix:CRITICAL:")
    assert len(out) == 1
    assert isinstance(out[0], PromptPrefixMutator)
    assert out[0].prefix == "CRITICAL:"


def test_parse_mutators_temperature() -> None:
    out = _parse_mutators("temperature:+0.2")
    assert isinstance(out[0], TemperatureMutator)
    assert out[0].delta == 0.2


def test_parse_mutators_multiple() -> None:
    out = _parse_mutators("identity,prompt-prefix:CRITICAL:")
    assert len(out) == 2


def test_parse_mutators_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown mutator"):
        _parse_mutators("bogus")


def test_parse_mutators_rejects_missing_temperature_delta() -> None:
    with pytest.raises(ValueError, match="float delta"):
        _parse_mutators("temperature:notanumber")


# ---- _load_evaluator --------------------------------------------------


def test_load_evaluator_none_returns_noop_default() -> None:
    eval_fn = _load_evaluator(None)
    out = eval_fn(object())
    assert out == {"pass_rate": 1.0}


def test_load_evaluator_invalid_spec_raises() -> None:
    with pytest.raises(ValueError, match="must be 'module:callable'"):
        _load_evaluator("nope")


def test_load_evaluator_resolves_module_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    monkeypatch.setattr(
        sys.modules[__name__], "_test_eval", _evaluator_always_passes,
        raising=False,
    )
    fn = _load_evaluator(f"{__name__}:_test_eval")
    assert fn(object()) == {"pass_rate": 1.0}


# ---- CLI end-to-end --------------------------------------------------


def _write_criterion(path: Path) -> None:
    path.write_text(
        "name: be-polite\n"
        "aggregation: all\n"
        "criteria:\n"
        "  - name: tests-pass\n"
        "    kind: pass_rate\n"
        "    target: 1.0\n"
        "    hard: true\n"
    )


def test_cli_improve_writes_snapshots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    monkeypatch.setattr(
        sys.modules[__name__], "_factory_attr", _factory, raising=False,
    )
    monkeypatch.setattr(
        sys.modules[__name__], "_eval_attr", _evaluator_prefix_wins, raising=False,
    )
    criterion_path = tmp_path / "crit.yaml"
    _write_criterion(criterion_path)
    output = tmp_path / "improved"

    rc = cli_main([
        "improve", f"{__name__}:_factory_attr",
        "--target", "orch",
        "--config", "prod",
        "--criteria", str(criterion_path),
        "--mutators", "identity,prompt-prefix:CRITICAL:",
        "--evaluator", f"{__name__}:_eval_attr",
        "--max-iters", "1",
        "--frontier", "2",
        "--output", str(output),
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "winners=" in out
    # At least one snapshot should land under improved/orch/.
    snaps = list((output / "orch").glob("*.json"))
    assert snaps, f"expected snapshots in {output / 'orch'}, found none"
    # LATEST.json mirrors a winner.
    latest = output / "orch" / "LATEST.json"
    assert latest.exists()


def test_cli_improve_rejects_unknown_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    monkeypatch.setattr(
        sys.modules[__name__], "_factory_attr", _factory, raising=False,
    )
    criterion_path = tmp_path / "crit.yaml"
    _write_criterion(criterion_path)
    rc = cli_main([
        "improve", f"{__name__}:_factory_attr",
        "--target", "no-such-agent",
        "--config", "prod",
        "--criteria", str(criterion_path),
        "--output", str(tmp_path / "improved"),
    ])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not present in resolved tree" in err
