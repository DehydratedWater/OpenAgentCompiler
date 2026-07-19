"""New starter lanes: telegram bot, batch runners, harness adapter, improve/."""

from __future__ import annotations

import ast
from pathlib import Path

from open_agent_compiler.scaffold.config import ScaffoldConfig
from open_agent_compiler.scaffold.engine import ScaffoldEngine, _file_map


def _config(tmp_path: Path, **kw) -> ScaffoldConfig:
    return ScaffoldConfig(target=tmp_path / "proj", project_name="proj", **kw)


def _render(tmp_path: Path, **kw):
    engine = ScaffoldEngine(config=_config(tmp_path, **kw))
    return engine.render()


def _assert_valid_python(path: Path) -> None:
    ast.parse(path.read_text())


def test_full_template_generates_the_telegram_bot_module(tmp_path: Path) -> None:
    """The compose file declares `python -m telegram_bot.bot` — the module
    must actually exist (this was a broken promise before)."""
    result = _render(tmp_path, template="full")
    target = result.target
    assert (target / "telegram_bot" / "__init__.py").exists()
    bot = target / "telegram_bot" / "bot.py"
    assert bot.exists()
    _assert_valid_python(bot)
    content = bot.read_text()
    assert "run_interactive" in content
    assert "chat_history" in content          # per-chat DB persistence
    assert "spawn_worker" in content          # worker dispatch tool
    compose = (target / "docker" / "docker-compose.yml").read_text()
    assert "telegram_bot.bot" in compose


def test_web_template_with_flag_also_gets_the_bot(tmp_path: Path) -> None:
    result = _render(tmp_path, template="web", with_telegram_bot=True)
    assert (result.target / "telegram_bot" / "bot.py").exists()


def test_web_template_without_flag_has_no_bot(tmp_path: Path) -> None:
    result = _render(tmp_path, template="web")
    assert not (result.target / "telegram_bot").exists()


def test_harness_adapter_carries_the_dialect(tmp_path: Path) -> None:
    result = _render(tmp_path, template="web", dialect="pi")
    harness = result.target / "app" / "harness.py"
    _assert_valid_python(harness)
    assert '"OAC_HARNESS", "pi"' in harness.read_text()


def test_batch_runner_lane_generated(tmp_path: Path) -> None:
    result = _render(tmp_path, template="web")
    batch = result.target / "runners" / "batch.py"
    _assert_valid_python(batch)
    assert "run_compiled_agent" in batch.read_text()
    jobs = result.target / "runners" / "jobs.json"
    import json
    assert isinstance(json.loads(jobs.read_text()), list)


def test_improve_starter_ships_with_every_template(tmp_path: Path) -> None:
    for template in ("barebones", "web", "full"):
        files = _file_map(_config(tmp_path, template=template))
        assert "improve/goals.yaml" in files
        assert "improve/run_improve.py" in files


def test_improve_runner_is_valid_python_and_reads_goals(tmp_path: Path) -> None:
    result = _render(tmp_path, template="barebones")
    runner = result.target / "improve" / "run_improve.py"
    _assert_valid_python(runner)
    content = runner.read_text()
    assert "run_per_target_loops" in content
    assert "build_compiled_evaluator" in content
    assert "build_interactive_evaluator" in content
    import yaml
    goals = yaml.safe_load((result.target / "improve" / "goals.yaml").read_text())
    assert goals["component"] == "primary"
    assert "opencode" in goals["targets"]


def test_generated_registry_supports_prompt_override(tmp_path: Path) -> None:
    result = _render(tmp_path, template="barebones")
    registry_py = (result.target / "agents" / "registry.py").read_text()
    assert "def registry(system_prompt: str | None = None)" in registry_py
    assert "STARTER_PROMPT" in registry_py
