"""Phase F: scaffold-generation tests for the `saas-personalized` template.

These assert the GENERATED files (the scaffold output), mirroring the existing
init/scaffold tests. They do NOT run any generated app live and do NOT touch
opencode/qwen/z.ai — they only inspect the emitted strings + parse them. A
separate assertion confirms the generated per-client tests are themselves
mocked (no live IO).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from open_agent_compiler.scaffold.config import ScaffoldConfig
from open_agent_compiler.scaffold.engine import ScaffoldEngine
from open_agent_compiler.scaffold.files import personalized, pyproject, readme


def _config(target: Path, **kw) -> ScaffoldConfig:
    kw.setdefault("template", "saas-personalized")
    kw.setdefault("llm", "zai-coding-plan")
    return ScaffoldConfig(target=target, **kw)


def _render(tmp_path: Path, **kw):
    target = tmp_path / "proj"
    result = ScaffoldEngine(config=_config(target, project_name="proj", **kw)).render()
    return target, result


# ---- config -------------------------------------------------------------


def test_template_value_is_accepted() -> None:
    cfg = ScaffoldConfig(target=Path("/tmp/x"), template="saas-personalized")
    assert cfg.is_personalized is True
    assert cfg.has_web_app is True  # personalized is a web-shaped template


def test_other_templates_are_not_personalized() -> None:
    for t in ("barebones", "web", "full"):
        cfg = ScaffoldConfig(target=Path("/tmp/x"), template=t)
        assert cfg.is_personalized is False
    assert ScaffoldConfig(target=Path("/tmp/x"), template="barebones").has_web_app is False


# ---- file tree ----------------------------------------------------------


def test_emits_expected_personalization_files(tmp_path: Path) -> None:
    target, result = _render(tmp_path)
    written = {p.relative_to(target).as_posix() for p in result.written_files}
    expected = {
        "personalization/__init__.py",
        "personalization/builtins.py",
        "personalization/elicit_runner.py",
        "personalization/client_agent.py",
        "personalization/orchestrate.py",
        "personalization/serving.py",
        "app/personalize.py",
        "scripts/personalize_client.py",
        "tests/test_personalization.py",
        "tests/test_adaptability.py",
        "config/settings.py",
        # the base fleet (replaces the single-agent starter)
        "agents/registry.py",
        "agents/__init__.py",
        # FastAPI app is emitted (web-shaped template)
        "app/main.py",
    }
    missing = expected - written
    assert not missing, f"missing generated files: {missing}"


def test_personalized_implies_fastapi_app(tmp_path: Path) -> None:
    """No --template web needed: saas-personalized emits the FastAPI app."""
    target, _ = _render(tmp_path)
    assert (target / "app" / "main.py").exists()
    assert (target / "run.py").exists()


def test_barebones_does_not_emit_personalization(tmp_path: Path) -> None:
    target = tmp_path / "bare"
    ScaffoldEngine(config=ScaffoldConfig(
        target=target, project_name="bare", template="barebones",
        llm="anthropic",
    )).render()
    assert not (target / "personalization").exists()
    assert not (target / "app" / "personalize.py").exists()


# ---- base fleet ---------------------------------------------------------


def test_fleet_registry_exposes_roles_and_factory(tmp_path: Path) -> None:
    target, _ = _render(tmp_path)
    src = (target / "agents" / "registry.py").read_text()
    assert "def build_fleet_registry(" in src
    assert "ROLES = (" in src
    # multi-role fleet (2-3 roles)
    assert '"planner"' in src and '"worker"' in src and '"critic"' in src
    # the per-client code's PERSONALIZED_ROLE must exist as a compiled role
    assert "also_compile_as_primary=True" in src
    # register_with_improvements so promotions merge transparently
    assert "register_with_improvements" in src
    # no-arg registry() for the oac CLI
    assert "def registry()" in src


def test_personalized_role_matches_a_fleet_role(tmp_path: Path) -> None:
    """The per-client loop tunes PERSONALIZED_ROLE; it must be a real fleet role."""
    target, _ = _render(tmp_path)
    agent_src = (target / "personalization" / "client_agent.py").read_text()
    fleet_src = (target / "agents" / "registry.py").read_text()
    # PERSONALIZED_ROLE = "planner"
    assert 'PERSONALIZED_ROLE = "planner"' in agent_src
    assert '"planner"' in fleet_src


# ---- the per-client flow wiring (chat→spec→merge→optimize→serve) --------


def test_client_agent_wires_the_full_framework_flow(tmp_path: Path) -> None:
    target, _ = _render(tmp_path)
    src = (target / "personalization" / "client_agent.py").read_text()
    # every framework API the design names
    for api in (
        "elicit_client_spec",
        "ClientCapabilityBundle",
        "profile_datasource",
        "apply_profile_to_datasource",
        "compile_personalized",
        "PersonalizationRun",
        "OpencodeRunner",
        "OpencodeMutatorClient",
        "flat_candidate_from_project_root",
    ):
        assert api in src, f"client_agent.py missing {api}"
    # per-client promotion bucket is referenced
    assert ".oac" in src


def test_api_router_exposes_intake_optimize_serve(tmp_path: Path) -> None:
    target, _ = _render(tmp_path)
    src = (target / "app" / "personalize.py").read_text()
    assert '"/intake"' in src
    assert '"/optimize"' in src
    assert '"/serve"' in src
    assert "personalize_client" in src


def test_app_main_includes_personalize_router(tmp_path: Path) -> None:
    target, _ = _render(tmp_path)
    main = (target / "app" / "main.py").read_text()
    assert "from app.personalize import router as personalize_router" in main
    assert "app.include_router(personalize_router)" in main


def test_serving_module_has_both_paths(tmp_path: Path) -> None:
    """Interactive (LangChain bind) + long-running (opencode session)."""
    target, _ = _render(tmp_path)
    src = (target / "personalization" / "serving.py").read_text()
    assert "bind_interactive_agent" in src
    assert "import build_interactive_spec, bind" in src
    assert "run_long_session" in src
    assert "OpencodeRunner" in src


def test_cli_script_runs_personalize_client(tmp_path: Path) -> None:
    target, _ = _render(tmp_path)
    src = (target / "scripts" / "personalize_client.py").read_text()
    assert "personalize_client" in src
    assert "--client-id" in src
    assert "--max-rounds" in src


# ---- opencode-only + secret hygiene (hard rules) ------------------------


def test_generated_code_uses_opencode_teacher_not_raw_provider(
    tmp_path: Path,
) -> None:
    target, _ = _render(tmp_path)
    elicit = (target / "personalization" / "elicit_runner.py").read_text()
    # teacher/judge go through the framework's opencode client
    assert "OpencodeMutatorClient" in elicit
    # no raw provider endpoints anywhere in the generated personalization code
    blob = "\n".join(
        p.read_text()
        for p in (target / "personalization").glob("*.py")
    )
    for forbidden in (
        "api.z.ai", "open.bigmodel.cn", "https://api.openai.com",
        "anthropic.Anthropic(", "import anthropic",
    ):
        assert forbidden not in blob, f"raw provider reference {forbidden!r} leaked"


def test_no_literal_secrets_in_generated_config(tmp_path: Path) -> None:
    target, _ = _render(tmp_path)
    settings = (target / "config" / "settings.py").read_text()
    # keys come from the environment only
    assert "os.environ" in settings
    # a long hex literal (a leaked api key) must not appear
    import re
    assert not re.search(r"[A-Fa-f0-9]{32,}", settings)


# ---- generated tests are MOCKED (no live IO) ----------------------------


def test_generated_tests_are_mocked(tmp_path: Path) -> None:
    target, _ = _render(tmp_path)
    src = (target / "tests" / "test_personalization.py").read_text()
    # fakes stand in for every IO seam
    assert "class FakeSessionRunner" in src
    assert "class FakeJudge" in src
    assert "class FakeTeacher" in src
    assert "class FakeElicitTeacher" in src
    # and it asserts the per-client promotion bucket
    assert ".oac" in src and "promoted" in src
    # no live network / subprocess in the generated test
    for forbidden in (
        "subprocess.run", "httpx.", "requests.get", "urllib.request.urlopen",
        "socket.", "OpencodeRunner(",
    ):
        assert forbidden not in src, f"generated test does live IO via {forbidden!r}"


def test_generated_tests_seed_probes_and_promote_per_client(
    tmp_path: Path,
) -> None:
    target, _ = _render(tmp_path)
    src = (target / "tests" / "test_personalization.py").read_text()
    assert "example_task:0" in src  # probes seeded from spec.example_tasks
    assert "promoted" in src and "CLIENT_ID" in src


# ---- generated ADAPTABILITY test (the platform-moat test) ---------------


def test_generated_adaptability_test_exists_and_is_mocked(tmp_path: Path) -> None:
    target, _ = _render(tmp_path)
    src = (target / "tests" / "test_adaptability.py").read_text()
    # ≥2 sharply different personas
    assert "PERSONA_A" in src and "PERSONA_B" in src
    assert "class Persona" in src
    # fully mocked: a fake stands in for every IO seam
    assert "class FakeSessionRunner" in src
    assert "class FakeElicitTeacher" in src
    assert "class PersonaJudge" in src
    assert "class PersonaTeacher" in src
    assert "class PersonaEnumerator" in src
    # asserts adaptation + the moat (same base fleet -> different winners)
    assert "test_personas_compile_to_distinct_surfaces" in src
    assert "test_same_base_fleet_adapts_differently_per_persona" in src
    assert "promoted" in src and ".oac" in src
    # no live network / subprocess / live runner in the generated test
    for forbidden in (
        "subprocess.run", "httpx.", "requests.get", "urllib.request.urlopen",
        "socket.", "OpencodeRunner(",
    ):
        assert forbidden not in src, f"generated adaptability test does live IO via {forbidden!r}"


# ---- everything parses --------------------------------------------------


def test_all_generated_python_parses(tmp_path: Path) -> None:
    _, result = _render(tmp_path)
    for p in result.written_files:
        if p.suffix == ".py":
            ast.parse(p.read_text(), filename=str(p))


# ---- per-generator content (no engine, pure string) ---------------------


def test_pyproject_adds_fastapi_and_langchain(tmp_path: Path) -> None:
    out = pyproject.render(_config(tmp_path, project_name="p"))
    assert '"fastapi>=' in out
    assert '"langchain-core>=' in out


def test_readme_documents_the_moat_and_flow(tmp_path: Path) -> None:
    out = readme.render(_config(tmp_path, project_name="p"))
    assert "Per-client personalization (the moat)" in out
    assert "/personalize/intake" in out
    assert "opencode-only" in out
    assert "chat → spec → merge → optimize → serve" in out


def test_builtins_generator_is_pure_data(tmp_path: Path) -> None:
    out = personalized.render_builtins(_config(tmp_path, project_name="p"))
    assert "BUILTIN_TOOLS" in out
    ast.parse(out)


# ---- CLI end-to-end -----------------------------------------------------


def test_cli_init_creates_personalized_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from open_agent_compiler.cli.main import main

    target = tmp_path / "p"
    rc = main([
        "init", str(target),
        "--name", "p",
        "--template", "saas-personalized",
        "--llm", "zai-coding-plan",
        "--no-uv-sync",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "scaffolded" in out
    assert (target / "personalization" / "client_agent.py").exists()
    assert (target / "app" / "personalize.py").exists()
    assert (target / "tests" / "test_personalization.py").exists()
