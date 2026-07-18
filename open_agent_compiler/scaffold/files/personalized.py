"""Generators for the `saas-personalized` template (Phase F).

These emit a repeatable, testable per-client agentic-SaaS starter that is
pre-wired to the framework's per-client auto-optimization (the
`PersonalizationRun` keystone). The shape mirrors a validated ad-generation
SaaS consumer's personalization layer: a base fleet + built-in tools, a
per-client personalization module (chat→ClientSpec → capability merge →
datasource auto-profile → `compile_personalized` → `PersonalizationRun` →
per-client `.oac/promoted/<client_id>/`), a FastAPI intake/personalize/serve
surface, a CLI, and mocked tests so the generated project ships green
per-client tests with NO live opencode/qwen/z.ai.

Every generator returns the file's full text. The whole module is pure data:
no IO, fully unit-testable by asserting on the emitted strings (which is what
the scaffold-generation tests do).
"""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


# --------------------------------------------------------------------------- #
# package + builtins                                                          #
# --------------------------------------------------------------------------- #


def render_package_init(config: ScaffoldConfig) -> str:
    return (
        '"""Per-client agent personalization for ' + config.project_name + '.\n'
        "\n"
        "Blends this SaaS's built-in tools with a client's own MCP tools +\n"
        "datasources and auto-optimizes a PRIVATE per-client agent against the\n"
        "client's stated workflow, using the framework's `PersonalizationRun`\n"
        "keystone. The autoloop is opencode-only (teacher/judge/student all via\n"
        "opencode — never a raw provider API).\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "from personalization.builtins import (\n"
        "    BUILTIN_TOOLS,\n"
        "    builtin_tools,\n"
        ")\n"
        "from personalization.client_agent import (\n"
        "    PERSONALIZED_ROLE,\n"
        "    build_client_bundle,\n"
        "    client_project_root,\n"
        "    compile_client_fleet,\n"
        "    elicit_spec,\n"
        "    make_agent_name_for,\n"
        "    optimize_client_agent,\n"
        "    serve_personalized_agent,\n"
        ")\n"
        "from personalization.elicit_runner import build_teacher, teacher_model\n"
        "from personalization.orchestrate import personalize_client\n"
        "\n"
        "__all__ = [\n"
        '    "BUILTIN_TOOLS",\n'
        '    "builtin_tools",\n'
        '    "PERSONALIZED_ROLE",\n'
        '    "build_client_bundle",\n'
        '    "client_project_root",\n'
        '    "compile_client_fleet",\n'
        '    "elicit_spec",\n'
        '    "make_agent_name_for",\n'
        '    "optimize_client_agent",\n'
        '    "serve_personalized_agent",\n'
        '    "build_teacher",\n'
        '    "teacher_model",\n'
        '    "personalize_client",\n'
        "]\n"
    )


def render_builtins(config: ScaffoldConfig) -> str:
    return (
        '"""The SaaS\'s built-in capability surface (the platform base tool set).\n'
        "\n"
        "These names are the built-in half of every client's\n"
        "`ClientCapabilityBundle`: a client's own MCP tools and datasources are\n"
        "merged ON TOP of these via `merge_capabilities`, so the personalized\n"
        "agent can reach both the platform's stock tools and the client's private\n"
        "surface. Pure data (a tuple of names) keeps the merge layer testable\n"
        "with no IO. Replace these with your product's real built-in tools.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "# Base SaaS tool names this platform contributes to every client's\n"
        "# merged surface. Each maps onto a real backend capability you expose.\n"
        "BUILTIN_TOOLS: tuple[str, ...] = (\n"
        '    "search_corpus",     # query the platform\'s shared knowledge base\n'
        '    "summarize",         # condense a document / result set\n'
        '    "export_report",     # render an answer into a delivery bundle\n'
        ")\n"
        "\n"
        "\n"
        "def builtin_tools() -> tuple[str, ...]:\n"
        '    """Return the platform\'s built-in tool name surface."""\n'
        "    return BUILTIN_TOOLS\n"
        "\n"
        "\n"
        '__all__ = ["BUILTIN_TOOLS", "builtin_tools"]\n'
    )


# --------------------------------------------------------------------------- #
# config/settings — model refs + per-client roots                            #
# --------------------------------------------------------------------------- #


def render_settings(config: ScaffoldConfig) -> str:
    return (
        '"""Runtime settings for the per-client personalization flow.\n'
        "\n"
        "Model refs come from the environment (`env:` refs only — never a literal\n"
        "key). The local student model is the same model the tuned agent serves\n"
        "on, and the teacher/judge is the strong GLM coding-plan model, used\n"
        "THROUGH opencode (never the raw provider API).\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "import os\n"
        "from dataclasses import dataclass\n"
        "from pathlib import Path\n"
        "\n"
        "PROJECT_ROOT = Path(__file__).resolve().parent.parent\n"
        "\n"
        "\n"
        "# NOT frozen: the per-client tests monkeypatch `agents_dir` to a temp\n"
        "# dir so the whole flow runs in isolation with no shared state.\n"
        "@dataclass\n"
        "class Settings:\n"
        '    """Resolved settings (read from the environment, with defaults)."""\n'
        "\n"
        "    # Where per-client opencode project roots live (one dir per tenant).\n"
        "    agents_dir: Path = PROJECT_ROOT / 'clients'\n"
        "    # The local vLLM student model the tuned agent serves on.\n"
        "    local_llm_model: str = os.environ.get(\n"
        "        'LOCAL_LLM_MODEL', 'cyankiwi/Qwen3.5-27B-AWQ-BF16-INT8',\n"
        "    )\n"
        "    # The teacher/judge model — routed via opencode's zai-coding-plan\n"
        "    # provider (NEVER the raw z.ai API).\n"
        "    teacher_model: str = os.environ.get('TEACHER_MODEL', 'glm-4.6')\n"
        "\n"
        "\n"
        "_SETTINGS: Settings | None = None\n"
        "\n"
        "\n"
        "def get_settings() -> Settings:\n"
        "    global _SETTINGS\n"
        "    if _SETTINGS is None:\n"
        "        _SETTINGS = Settings()\n"
        "    return _SETTINGS\n"
        "\n"
        "\n"
        '__all__ = ["Settings", "get_settings", "PROJECT_ROOT"]\n'
    )


# --------------------------------------------------------------------------- #
# elicit_runner — the opencode teacher/judge client                          #
# --------------------------------------------------------------------------- #


def render_elicit_runner(config: ScaffoldConfig) -> str:
    return (
        '"""Build the opencode teacher/judge client for the personalization loop.\n'
        "\n"
        "The autoloop's teacher (spec elicitation + prompt rewrite) and judge BOTH\n"
        "route through opencode via the framework's `OpencodeMutatorClient` — GLM\n"
        "on the z.ai coding plan, used THROUGH opencode (NEVER the raw provider\n"
        "API). This module is the single place the teacher is constructed, so the\n"
        "model ref + workspace wiring live in one spot and tests swap it for a\n"
        "fake.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "from pathlib import Path\n"
        "\n"
        "from open_agent_compiler.improvement.mutators.opencode_teacher import OpencodeMutatorClient\n"
        "\n"
        "from config.settings import get_settings\n"
        "\n"
        "# Default teacher/judge model — the strong GLM coding-plan model, routed\n"
        "# via opencode's `zai-coding-plan` provider (bare name is normalized to\n"
        "# `zai-coding-plan/<name>` by OpencodeMutatorClient).\n"
        'DEFAULT_TEACHER_MODEL = "glm-4.6"\n'
        "\n"
        "\n"
        "def teacher_model() -> str:\n"
        '    """The teacher/judge model ref (override via TEACHER_MODEL env)."""\n'
        "    return get_settings().teacher_model or DEFAULT_TEACHER_MODEL\n"
        "\n"
        "\n"
        "def build_teacher(workspace: Path) -> OpencodeMutatorClient:\n"
        '    """Construct an `OpencodeMutatorClient` rooted in `workspace`.\n'
        "\n"
        "    `workspace` must be an opencode project root (holds `opencode.json`) —\n"
        "    the per-client project root from `compile_client_fleet` satisfies\n"
        "    this. All teacher/judge completions run THROUGH opencode; no raw\n"
        "    provider API is ever touched.\n"
        '    """\n'
        "    return OpencodeMutatorClient(workspace=Path(workspace), model=teacher_model())\n"
        "\n"
        "\n"
        '__all__ = ["DEFAULT_TEACHER_MODEL", "teacher_model", "build_teacher"]\n'
    )


# --------------------------------------------------------------------------- #
# client_agent — build / compile / optimize / serve                          #
# --------------------------------------------------------------------------- #


def render_client_agent(config: ScaffoldConfig) -> str:
    return _CLIENT_AGENT_TEMPLATE.replace("{{project_name}}", config.project_name)


def render_orchestrate(config: ScaffoldConfig) -> str:
    return _ORCHESTRATE_TEMPLATE


def render_serving(config: ScaffoldConfig) -> str:
    return _SERVING_TEMPLATE


def render_api_router(config: ScaffoldConfig) -> str:
    return _API_ROUTER_TEMPLATE.replace("{{project_name}}", config.project_name)


def render_cli_script(config: ScaffoldConfig) -> str:
    return _CLI_TEMPLATE


def render_tests(config: ScaffoldConfig) -> str:
    return _TESTS_TEMPLATE


def render_adaptability_tests(config: ScaffoldConfig) -> str:
    """The generated per-client ADAPTABILITY test (the platform-moat test).

    Ships ≥2 sharply different mocked personas and asserts the generated
    project's personalization structure ADAPTS to each (different merged tool
    surface, different compiled prompt, a different persona-shaped promoted
    winner from the SAME base fleet) — fully mocked, no live opencode/qwen/z.ai.
    """
    return _ADAPTABILITY_TESTS_TEMPLATE


def render_fleet_registry(config: ScaffoldConfig) -> str:
    """The base agent fleet for the saas-personalized template.

    A 2-3 role fleet (planner / worker / critic) exposing
    `build_fleet_registry(model_name=...)` + `ROLES` (what the personalization
    module compiles against) AND a no-arg `registry()` (what `oac compile /
    test / improve` resolve via `agents:registry`). Each role compiles to a
    `<role>-primary.md` (via `also_compile_as_primary=True`) so the per-client
    code can read `planner-primary.md`.
    """
    return _FLEET_REGISTRY_TEMPLATE.replace(
        "{{project_name}}", config.project_name,
    ).replace("{{default_model}}", _default_model_ref(config))


def render_fleet_package_init(config: ScaffoldConfig) -> str:
    return (
        f'"""Agent fleet for {config.project_name} (saas-personalized).\n\n'
        "Exposes `build_fleet_registry`, `ROLES`, and a no-arg `registry()`\n"
        "factory the `oac` CLI resolves via `agents:registry`.\n"
        '"""\n\n'
        "from agents.registry import ROLES, build_fleet_registry, registry\n\n"
        '__all__ = ["ROLES", "build_fleet_registry", "registry"]\n'
    )


def _default_model_ref(config: ScaffoldConfig) -> str:
    return {
        "anthropic": "anthropic/claude-sonnet-4-5-20250929",
        "openai": "openai/gpt-4o-mini",
        "openrouter": "openrouter/anthropic/claude-sonnet-4.5",
        "vllm": "vllm/cyankiwi/Qwen3.5-27B-AWQ-BF16-INT8",
        "zai-coding-plan": "zai-coding-plan/glm-4.5-air",
    }[config.llm]


# --------------------------------------------------------------------------- #
# big templates (kept as module-level raw strings for readability)            #
# --------------------------------------------------------------------------- #


_CLIENT_AGENT_TEMPLATE = '''"""Per-client personalized agent — build, optimize, and serve.

This is the integration onto the framework's per-client auto-optimization (the
`PersonalizationRun` keystone). The platform thesis: a client connects their own
MCP tools + datasources (e.g. a private Google Drive) and describes their
workflow in chat, and the platform auto-optimizes a PRIVATE agent that blends
the SaaS's built-in tools with the client's, tuned to the client's stated goal —
deep tool-use optimization, not prompt tweaks.

The flow (all framework APIs; the autoloop is opencode-only — no raw provider):

  1. `elicit_client_spec(chat, teacher)` — chat -> validated ClientSpec
     (teacher = `OpencodeMutatorClient`, GLM via opencode; NEVER a raw API).
  2. `build_client_bundle(...)` — ClientCapabilityBundle = built-ins ∪ client
     MCP tools ∪ client datasources, each datasource auto-profiled
     (`profile_datasource`) with its derived tools folded in.
  3. `compile_personalized(...)` against the base fleet factory -> a per-client
     opencode project root (merged opencode.json: client MCP + built-in surface,
     spec-derived prompt overlay + datasource context on every role).
  4. `PersonalizationRun(...).run(...)` -> deep-tool-use optimization over the
     joint mutation space; winners promote PER-CLIENT into
     `.oac/promoted/<client_id>/`.
  5. `serve_personalized_agent(client_id, ...)` — recompile with the client's
     promotions applied and return the served agent dir + role names.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from open_agent_compiler import (
    ClientCapabilityBundle,
    ClientDatasource,
    ClientMCPServer,
    ClientSpec,
    PersonalizationRun,
    apply_profile_to_datasource,
    compile_personalized,
    elicit_client_spec,
    profile_datasource,
)
from open_agent_compiler.datasource.adapter import DatasourceAdapter
from open_agent_compiler.datasource.profile import DatasourceProfile
from open_agent_compiler.improvement.compile_helpers import flat_candidate_from_project_root
from open_agent_compiler.improvement.mutators.opencode_teacher import OpencodeMutatorClient
from open_agent_compiler.improvement.opencode_eval import OpencodeRunner
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults

from agents.registry import ROLES, build_fleet_registry
from personalization.builtins import builtin_tools
from config.settings import get_settings

log = logging.getLogger("{{project_name}}.personalization")

# The role we optimize per client. Tune the role with the highest leverage on
# the workflow; extend to per-role loops later.
PERSONALIZED_ROLE = "planner"


# --------------------------------------------------------------------------- #
# 0. paths                                                                     #
# --------------------------------------------------------------------------- #


def client_project_root(client_id: str) -> Path:
    """Per-client opencode project root (one root per tenant = full isolation).

    Holds the compiled fleet (`.opencode/agents/`), the merged `opencode.json`,
    seeded probes (`.oac/<client_id>/`), and promotions
    (`.oac/promoted/<client_id>/`).
    """
    return get_settings().agents_dir / "clients" / client_id


# --------------------------------------------------------------------------- #
# 1. chat -> ClientSpec                                                        #
# --------------------------------------------------------------------------- #


def elicit_spec(
    chat_transcript: str,
    teacher: OpencodeMutatorClient,
    *,
    require_usable: bool = True,
) -> ClientSpec:
    """Distil the client's chat into a validated `ClientSpec` via the teacher.

    `teacher` is an `OpencodeMutatorClient` (GLM via opencode) — the ONLY IO
    seam, always mocked in tests.
    """
    return elicit_client_spec(
        chat_transcript, teacher, require_usable=require_usable,
    )


# --------------------------------------------------------------------------- #
# 2. capability merge (built-ins ∪ client MCP ∪ datasources)                   #
# --------------------------------------------------------------------------- #


def build_client_bundle(
    client_id: str,
    *,
    mcp_servers: tuple[ClientMCPServer, ...] = (),
    datasources: tuple[ClientDatasource, ...] = (),
    datasource_adapters: dict[str, DatasourceAdapter] | None = None,
    sample_n: int = 5,
) -> tuple[ClientCapabilityBundle, tuple[DatasourceProfile, ...]]:
    """Assemble the client's capability bundle + auto-profile each datasource.

    Returns `(bundle, profiles)`. For every datasource that has an adapter in
    `datasource_adapters` (keyed by `ClientDatasource.name`) we
    `profile_datasource(adapter)` to learn its structure and
    `apply_profile_to_datasource(...)` to fold the derived tool names onto the
    datasource — so they flow through `merge_capabilities` on equal footing with
    built-in and client MCP tools. The adapter's enumerator is the only IO seam
    (a real MCP in prod, a mock in tests).
    """
    adapters = datasource_adapters or {}
    profiles: list[DatasourceProfile] = []
    enriched: list[ClientDatasource] = []
    for ds in datasources:
        adapter = adapters.get(ds.name)
        if adapter is None:
            enriched.append(ds)
            continue
        profile = profile_datasource(adapter, sample_n=sample_n)
        profiles.append(profile)
        enriched.append(apply_profile_to_datasource(ds, profile))
        log.info(
            "profiled datasource %s for client %s: %d containers / %d leaves",
            ds.name, client_id, profile.container_count, profile.leaf_count,
        )

    bundle = ClientCapabilityBundle(
        client_id=client_id,
        builtin_tools=builtin_tools(),
        mcp_servers=mcp_servers,
        datasources=tuple(enriched),
    )
    return bundle, tuple(profiles)


# --------------------------------------------------------------------------- #
# 3. personalized compile (per-client opencode project root)                  #
# --------------------------------------------------------------------------- #


def _local_preset() -> ModelPreset:
    """The local-qwen student preset the personalized fleet compiles against.

    The autoloop tunes the agent on the SAME model that will serve it, so the
    overlay's preset points at the local model (temp 1.0 / top_p 0.95 / top_k 20
    per the framework's local-qwen guidance).
    """
    settings = get_settings()
    return ModelPreset(
        name="local-student",
        provider="vllm",
        model_id=settings.local_llm_model,
        sampling=SamplingDefaults(temperature=1.0, top_p=0.95, top_k=20),
    )


def compile_client_fleet(
    client_id: str,
    spec: ClientSpec,
    bundle: ClientCapabilityBundle,
    *,
    model_name: str | None = None,
    datasource_profiles: tuple[DatasourceProfile, ...] = (),
    target_dir: Path | None = None,
):
    """Compile the base fleet personalized for one client.

    Wraps `compile_personalized` against `build_fleet_registry` (the SAME
    factory the base runtime uses). The result's `opencode.json` carries the
    client's MCP servers + the merged allow-list (built-ins ∪ client tools),
    each role's prompt carries the client overlay (goal/preferences/constraints)
    + each datasource's auto-profiled layout, and `client_id` flows into the
    CompilationContext so per-client promotions are consulted on recompile.
    """
    settings = get_settings()
    model = model_name or settings.local_llm_model
    target = target_dir or client_project_root(client_id)
    target.mkdir(parents=True, exist_ok=True)

    def factory():
        return build_fleet_registry(model_name=model)

    compiled = compile_personalized(
        client_id, spec, bundle, target,
        factory=factory, config="prod", preset=_local_preset(),
        datasource_profiles=datasource_profiles,
    )
    log.info(
        "compiled personalized fleet for client %s -> %s (mcp=%s, tools=%d)",
        client_id, compiled.project_root,
        list(compiled.mcp_servers), len(compiled.allow_list),
    )
    return compiled


# --------------------------------------------------------------------------- #
# 4. the per-client optimization loop                                         #
# --------------------------------------------------------------------------- #


def make_agent_name_for(
    compiled,
    *,
    model: str | None = None,
) -> Callable[[ComponentVersion], str]:
    """The ONE live integration callback: candidate -> installed flat agent name.

    The optimization loop calls this for every candidate. It writes the
    candidate's tuned system_prompt as a flat opencode agent (`cand_<hex>.md`)
    into the client's project root via `flat_candidate_from_project_root`, so the
    `OpencodeRunner` can discover and run THAT candidate as a full session.
    """
    base_md = compiled.agents_dir / f"{PERSONALIZED_ROLE}-primary.md"
    base_text = base_md.read_text(encoding="utf-8") if base_md.exists() else ""

    def agent_name_for(version: ComponentVersion) -> str:
        system_prompt = version.definition.get("system_prompt", "")
        md_text = _swap_body(base_text, system_prompt)
        return flat_candidate_from_project_root(
            project_root=compiled.project_root,
            md_text=md_text,
            model=model,
        )

    return agent_name_for


def _swap_body(base_md_text: str, system_prompt: str) -> str:
    """Replace a compiled agent .md's body with `system_prompt`.

    Keeps the YAML frontmatter (model + tool permissions) so the candidate runs
    with the merged tool surface intact.
    """
    if base_md_text.startswith("---"):
        end = base_md_text.find("\\n---", 3)
        if end != -1:
            frontmatter = base_md_text[: end + len("\\n---")]
            return f"{frontmatter}\\n{system_prompt}\\n"
    return f"---\\n---\\n{system_prompt}\\n"


def optimize_client_agent(
    client_id: str,
    spec: ClientSpec,
    bundle: ClientCapabilityBundle,
    compiled,
    *,
    runner: OpencodeRunner,
    judge: OpencodeMutatorClient,
    teacher: OpencodeMutatorClient,
    datasource_profiles: tuple[DatasourceProfile, ...] = (),
    target: float = 0.7,
    max_rounds: int = 3,
    agent_name_for: Callable[[ComponentVersion], str] | None = None,
):
    """Run the per-client deep-tool-use optimization loop.

    Seeds probes from `spec.example_tasks`, builds the joint mutation space
    (prompt+workflow AND tool selection/sequence/description/rule/format) from
    the spec + the client's tool names, evaluates every candidate as a FULL
    opencode session graded against `spec.success_criteria`, and promotes
    winners into `.oac/promoted/<client_id>/`.

    `runner` / `judge` / `teacher` are an `OpencodeRunner` +
    `OpencodeMutatorClient` (or fakes exposing the same surface). All three route
    through opencode — no raw provider API anywhere in this loop.
    """
    baseline = _baseline_definition(compiled)
    name_for = agent_name_for or make_agent_name_for(compiled)

    run = PersonalizationRun(
        client_id=client_id,
        client_spec=spec,
        capability_bundle=bundle,
        datasource_profiles=datasource_profiles,
        target=target,
        max_rounds=max_rounds,
    )
    result = run.run(
        baseline_definition=baseline,
        runner=runner,
        judge=judge,
        teacher=teacher,
        agent_name_for=name_for,
        project_root=compiled.project_root,
        snapshots_dir=compiled.project_root / ".oac" / "snapshots",
    )
    log.info(
        "personalization run for client %s: promoted=%s score=%.2f -> %s",
        client_id, result.promoted, result.winner_score, result.promoted_path,
    )
    return result


def _baseline_definition(compiled) -> dict[str, Any]:
    """The personalized role's compiled definition as the loop baseline."""
    md = compiled.agents_dir / f"{PERSONALIZED_ROLE}-primary.md"
    system_prompt = ""
    if md.exists():
        text = md.read_text(encoding="utf-8")
        if text.startswith("---"):
            end = text.find("\\n---", 3)
            if end != -1:
                system_prompt = text[end + len("\\n---"):].strip()
        else:
            system_prompt = text.strip()
    return {
        "header": {"agent_id": PERSONALIZED_ROLE},
        "system_prompt": system_prompt,
    }


# --------------------------------------------------------------------------- #
# 5. serve the optimized per-client agent                                     #
# --------------------------------------------------------------------------- #


def serve_personalized_agent(
    client_id: str,
    spec: ClientSpec,
    bundle: ClientCapabilityBundle,
    *,
    model_name: str | None = None,
    datasource_profiles: tuple[DatasourceProfile, ...] = (),
    target_dir: Path | None = None,
) -> dict[str, Any]:
    """Compile + serve a client's optimized agent, applying its promotions.

    A re-compile picks up `.oac/promoted/<client_id>/` automatically (the
    `client_id` flows into the CompilationContext). Returns
    `{agent_dir, model, roles, mcp_servers, tools, client_id}`.
    """
    compiled = compile_client_fleet(
        client_id, spec, bundle,
        model_name=model_name,
        datasource_profiles=datasource_profiles, target_dir=target_dir,
    )
    settings = get_settings()
    return {
        "client_id": client_id,
        "agent_dir": str(compiled.project_root),
        "model": model_name or settings.local_llm_model,
        "roles": {role: f"{role}-primary" for role in ROLES},
        "mcp_servers": list(compiled.mcp_servers),
        "tools": list(compiled.allow_list),
    }


__all__ = [
    "PERSONALIZED_ROLE",
    "client_project_root",
    "elicit_spec",
    "build_client_bundle",
    "compile_client_fleet",
    "make_agent_name_for",
    "optimize_client_agent",
    "serve_personalized_agent",
]
'''


_ORCHESTRATE_TEMPLATE = '''"""End-to-end per-client personalization orchestration (the real run entry).

`personalize_client(...)` runs the whole pipeline for one client:

    chat transcript + connected MCP/datasource configs
      -> elicit ClientSpec (teacher via opencode)
      -> merge capabilities + auto-profile datasources
      -> compile the personalized fleet (per-client opencode root)
      -> optimize via PersonalizationRun (deep tool-use, opencode-only)
      -> serve: recompile applying the client's promotions

It constructs the live opencode IO seams (`OpencodeRunner` + two
`OpencodeMutatorClient`s rooted in the client project) by default, but every
seam is injectable so the whole orchestration is unit-tested with fakes and NO
live opencode/qwen/z.ai/network. This is the function the CLI/endpoint calls to
run a REAL optimization once the shared qwen is free.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from open_agent_compiler import ClientDatasource, ClientMCPServer, ClientSpec
from open_agent_compiler.datasource.adapter import DatasourceAdapter
from open_agent_compiler.improvement.opencode_eval import OpencodeRunner
from open_agent_compiler.improvement.mutators.opencode_teacher import OpencodeMutatorClient

from personalization.client_agent import (
    build_client_bundle,
    client_project_root,
    compile_client_fleet,
    elicit_spec,
    make_agent_name_for,
    optimize_client_agent,
    serve_personalized_agent,
)
from personalization.elicit_runner import build_teacher
from config.settings import get_settings

log = logging.getLogger("personalization.orchestrate")


def personalize_client(
    client_id: str,
    chat_transcript: str,
    *,
    mcp_servers: tuple[ClientMCPServer, ...] = (),
    datasources: tuple[ClientDatasource, ...] = (),
    datasource_adapters: dict[str, DatasourceAdapter] | None = None,
    target: float = 0.7,
    max_rounds: int = 3,
    optimize: bool = True,
    # ---- injectable seams (defaults build the live opencode clients) -------
    teacher: OpencodeMutatorClient | None = None,
    judge: OpencodeMutatorClient | None = None,
    runner: OpencodeRunner | None = None,
    elicit_teacher: Any | None = None,
    teacher_factory: Callable[[Path], OpencodeMutatorClient] | None = None,
) -> dict[str, Any]:
    """Run the full per-client personalization pipeline. Returns a result dict.

    All opencode seams default to live clients rooted in the client project, but
    are injectable for tests. When `optimize=False` the loop is skipped (compile
    + serve only) — useful for a dry compile/serve of the merged surface.

    Returns `{client_id, spec, served, run}` where `served` is the serve
    descriptor and `run` is the PersonalizationRunResult (or None).
    """
    settings = get_settings()
    tfactory = teacher_factory or build_teacher

    # 1. chat -> ClientSpec, via the opencode teacher (mocked in tests).
    root = client_project_root(client_id)
    root.mkdir(parents=True, exist_ok=True)
    el_teacher = elicit_teacher or tfactory(root)
    spec: ClientSpec = elicit_spec(chat_transcript, el_teacher, require_usable=True)
    log.info("elicited spec for client %s: goal=%r", client_id, spec.goal)

    # 2. capability merge + datasource auto-profiling.
    bundle, profiles = build_client_bundle(
        client_id,
        mcp_servers=mcp_servers,
        datasources=datasources,
        datasource_adapters=datasource_adapters,
    )

    # 3. personalized compile (per-client opencode project root).
    compiled = compile_client_fleet(
        client_id, spec, bundle,
        datasource_profiles=profiles, target_dir=root,
    )

    run_result = None
    if optimize:
        # 4. live opencode seams (or injected fakes) + the optimization loop.
        live_runner = runner or OpencodeRunner(build_dir=compiled.project_root)
        live_teacher = teacher or tfactory(compiled.project_root)
        live_judge = judge or tfactory(compiled.project_root)
        run_result = optimize_client_agent(
            client_id, spec, bundle, compiled,
            runner=live_runner, judge=live_judge, teacher=live_teacher,
            datasource_profiles=profiles, target=target, max_rounds=max_rounds,
            agent_name_for=make_agent_name_for(
                compiled, model=settings.local_llm_model,
            ),
        )

    # 5. serve: recompile applying the client's promotions.
    served = serve_personalized_agent(
        client_id, spec, bundle,
        datasource_profiles=profiles, target_dir=root,
    )

    return {
        "client_id": client_id,
        "spec": spec,
        "served": served,
        "run": run_result,
    }


__all__ = ["personalize_client"]
'''


_SERVING_TEMPLATE = '''"""Serve a client's optimized agent — interactive + long-running paths.

Two serving paths the framework already provides:

  * INTERACTIVE / quick (chat, sub-30s): build a LangChain runnable via
    `bind(spec)` over the served role's `InteractiveAgentSpec` and stream it.
  * LONG-RUNNING (multi-step, tool-heavy): hand the compiled per-client project
    root to an `OpencodeRunner` and run a full opencode session.

Both consume the SAME per-client compiled artifact produced by
`serve_personalized_agent` (which already applied the client's promotions), so
the served agent is the auto-optimized one. The interactive `bind` import is
lazy so the module loads without langchain installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def bind_interactive_agent(
    *,
    system_prompt: str,
    model_name: str,
    tool_runner: Any | None = None,
    api_key: str | None = None,
    streaming: bool = True,
):
    """Build a LangChain LCEL runnable for the served agent (interactive path).

    Wraps the framework's `build_interactive_spec` + `bind`. Invoke/stream with
    `{"messages": [...]}`. The system_prompt is the client's optimized prompt
    (read from the served agent .md), so quick chats use the tuned agent.
    """
    from open_agent_compiler import build_interactive_spec, bind

    spec = build_interactive_spec(
        agent_id="served",
        system_prompt=system_prompt,
        model_name=model_name,
    )
    return bind(spec, tool_runner=tool_runner, api_key=api_key, streaming=streaming)


def run_long_session(
    *,
    project_root: Path,
    agent_name: str,
    prompt: str,
    runner: Any | None = None,
):
    """Run a full opencode session for the served agent (long-running path).

    `runner` defaults to a live `OpencodeRunner` rooted in the client's compiled
    project (so the merged tool surface + promotions are live); inject a fake in
    tests. Returns the runner's result (final text + tool-use trajectory).
    """
    if runner is None:
        from open_agent_compiler.improvement.opencode_eval import OpencodeRunner

        runner = OpencodeRunner(build_dir=Path(project_root))
    return runner.run(agent_name=agent_name, prompt=prompt)


def served_system_prompt(project_root: Path, role: str) -> str:
    """Read the served role's optimized system prompt from its compiled .md."""
    md = Path(project_root) / ".opencode" / "agents" / f"{role}-primary.md"
    if not md.exists():
        return ""
    text = md.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\\n---", 3)
        if end != -1:
            return text[end + len("\\n---"):].strip()
    return text.strip()


__all__ = [
    "bind_interactive_agent",
    "run_long_session",
    "served_system_prompt",
]
'''


_API_ROUTER_TEMPLATE = '''"""Per-client personalization endpoints (Phase F).

Exposes the per-client flow over HTTP:

  * POST /personalize/intake   — collect chat requirements -> ClientSpec preview.
  * POST /personalize/optimize — run the PersonalizationRun for a client_id
                                  (deep tool-use loop; opencode-only).
  * POST /personalize/serve    — compile+serve the client's optimized agent
                                  (applies `.oac/promoted/<client_id>/`),
                                  returning the interactive + long-running
                                  serving handles.

The heavy optimize loop needs the shared qwen + can take minutes; in production
you'll typically launch it out of band (the CLI / a worker) and keep /serve
inline. Every handler defers to `personalization.personalize_client`, whose IO
seams are injectable + fully mocked in tests.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/personalize", tags=["personalize"])
log = logging.getLogger("{{project_name}}.api.personalize")


class ClientToolIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    transport: str = Field(default="remote", max_length=40)
    url: str = Field(default="", max_length=2000)
    tools: list[str] = Field(default_factory=list)


class IntakeIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    chat_transcript: str = Field(min_length=1, max_length=20000)


class SpecOut(BaseModel):
    client_id: str
    goal: str
    preferences: list[str]
    constraints: list[str]
    example_tasks: list[str]
    success_criteria: list[str]


class OptimizeIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    chat_transcript: str = Field(min_length=1, max_length=20000)
    mcp_servers: list[ClientToolIn] = Field(default_factory=list)
    target: float = 0.7
    max_rounds: int = 3


class ServeIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    chat_transcript: str = Field(min_length=1, max_length=20000)
    mcp_servers: list[ClientToolIn] = Field(default_factory=list)


class ServeOut(BaseModel):
    client_id: str
    agent_dir: str
    model: str
    roles: dict[str, str]
    mcp_servers: list[str]
    tools: list[str]
    goal: str
    promoted: bool = False
    winner_score: float | None = None


def _to_mcp_servers(items: list[ClientToolIn]):
    from open_agent_compiler import ClientMCPServer

    return tuple(
        ClientMCPServer(
            name=i.name, transport=i.transport, url=i.url, tools=tuple(i.tools),
        )
        for i in items
    )


@router.post("/intake", response_model=SpecOut)
async def intake(body: IntakeIn) -> SpecOut:
    """Collect chat requirements -> a ClientSpec preview (no compile/loop)."""
    from personalization import build_teacher, client_project_root, elicit_spec

    root = client_project_root(body.client_id)
    root.mkdir(parents=True, exist_ok=True)
    try:
        spec = elicit_spec(body.chat_transcript, build_teacher(root))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SpecOut(
        client_id=body.client_id,
        goal=spec.goal,
        preferences=list(spec.preferences),
        constraints=list(spec.constraints),
        example_tasks=[t.prompt for t in spec.example_tasks],
        success_criteria=list(spec.success_criteria),
    )


@router.post("/optimize", response_model=ServeOut)
async def optimize(body: OptimizeIn) -> ServeOut:
    """Run the per-client deep-tool-use optimization loop, then serve."""
    from personalization import personalize_client

    try:
        result = personalize_client(
            body.client_id, body.chat_transcript,
            mcp_servers=_to_mcp_servers(body.mcp_servers),
            target=body.target, max_rounds=body.max_rounds,
            optimize=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serve_out(result)


@router.post("/serve", response_model=ServeOut)
async def serve(body: ServeIn) -> ServeOut:
    """Compile + serve a client's optimized agent (promotions applied).

    The optimization loop itself runs out of band (`/optimize` or the CLI); this
    endpoint just compiles + applies any promoted per-client snapshots so the
    existing run path can invoke the tuned agent.
    """
    from personalization import personalize_client

    try:
        result = personalize_client(
            body.client_id, body.chat_transcript,
            mcp_servers=_to_mcp_servers(body.mcp_servers),
            optimize=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serve_out(result)


def _serve_out(result) -> ServeOut:
    served = result["served"]
    run = result.get("run")
    return ServeOut(
        client_id=served["client_id"],
        agent_dir=served["agent_dir"],
        model=served["model"],
        roles=served["roles"],
        mcp_servers=served["mcp_servers"],
        tools=served["tools"],
        goal=result["spec"].goal,
        promoted=bool(run.promoted) if run is not None else False,
        winner_score=run.winner_score if run is not None else None,
    )
'''


_CLI_TEMPLATE = '''#!/usr/bin/env python3
"""Run a REAL per-client agent optimization (Phase F).

Drives the full pipeline LIVE: elicit ClientSpec from a chat transcript
(teacher = GLM via opencode), merge the platform's built-in tools with the
client's MCP servers + datasources, auto-profile each datasource, compile the
personalized fleet, run the deep-tool-use PersonalizationRun (teacher + judge
via opencode, student via local qwen through OpencodeRunner), and serve the
optimized agent with its per-client promotions applied.

PRE-FLIGHT (the autoloop is opencode-only — never a raw provider API):
  * the local qwen vLLM endpoint must be UP and FREE;
  * `opencode` CLI must be on PATH and authed for the zai-coding-plan provider
    (`ZAI_API_KEY` in the gitignored .env / opencode auth);
  * run from the host (opencode does not work inside the Docker backend).

USAGE (host, framework on PYTHONPATH):
  PYTHONPATH=/path/to/oac:. \\\\
  ZAI_API_KEY=... \\\\
  python scripts/personalize_client.py \\\\
      --client-id acme \\\\
      --chat path/to/chat_transcript.txt \\\\
      --mcp-url https://mcp.example/acme/drive \\\\
      --mcp-tools drive_search,drive_read \\\\
      --max-rounds 3 --target 0.7

Omit --mcp-url to run with platform built-ins only. Promotions land at
  clients/clients/<client_id>/.oac/promoted/<client_id>/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _read_chat(value: str) -> str:
    p = Path(value)
    return p.read_text(encoding="utf-8") if p.exists() else value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run a real per-client optimization.")
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--chat", required=True, help="Chat transcript text or a file path.")
    ap.add_argument("--mcp-url", default="", help="Remote client MCP URL (optional).")
    ap.add_argument("--mcp-tools", default="drive_search,drive_read")
    ap.add_argument("--target", type=float, default=0.7)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--no-optimize", action="store_true", help="Compile+serve only.")
    args = ap.parse_args(argv)

    from open_agent_compiler import ClientDatasource, ClientMCPServer

    from personalization import personalize_client

    mcp_servers: tuple = ()
    datasources: tuple = ()
    if args.mcp_url:
        tools = tuple(t.strip() for t in args.mcp_tools.split(",") if t.strip())
        server = ClientMCPServer(
            name=f"{args.client_id}_mcp", transport="remote",
            url=args.mcp_url, tools=tools,
        )
        ds = ClientDatasource(
            name=f"{args.client_id}_ds", kind="gdrive",
            mcp_server_name=server.name,
        )
        mcp_servers = (server,)
        datasources = (ds,)
        # A real MCP enumerator over the client's datasource would attach here as
        # a `MCPDatasourceAdapter`; until then profiling is skipped for this
        # datasource (still wired into opencode.json).

    result = personalize_client(
        args.client_id, _read_chat(args.chat),
        mcp_servers=mcp_servers, datasources=datasources,
        target=args.target, max_rounds=args.max_rounds,
        optimize=not args.no_optimize,
    )

    spec = result["spec"]
    run = result["run"]
    served = result["served"]
    print(f"\\n=== client {args.client_id} ===")
    print(f"goal: {spec.goal}")
    print(f"merged tools: {served['tools']}")
    print(f"mcp servers: {served['mcp_servers']}")
    if run is not None:
        print(f"optimized: promoted={run.promoted} score={run.winner_score:.2f}")
        print(f"promotion: {run.promoted_path}")
    print(f"served agent dir: {served['agent_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


_TESTS_TEMPLATE = '''"""Per-client personalization (Phase F) — fully MOCKED, no live IO.

A fake OpencodeRunner + teacher/judge stand in for opencode/qwen/z.ai so the
whole per-client flow is asserted with NO network. Covers:

  * built-in tools ∪ client MCP ∪ datasource tools merged into the personalized
    opencode.json (the merged surface the loop runs from);
  * the spec is seeded from the chat transcript (teacher mocked);
  * datasource auto-profiling folds derived tools into the bundle + injects the
    layout into the compiled prompt;
  * a PersonalizationRun promotes a winner into .oac/promoted/<client_id>/;
  * make_agent_name_for installs flat candidates the runner can discover;
  * the served agent picks up the per-client promotion.

This ships GREEN out of the box: `uv run pytest tests/test_personalization.py`.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("ZAI_API_KEY", "test-key")

import pytest  # noqa: E402

from open_agent_compiler import ClientDatasource, ClientMCPServer  # noqa: E402
from open_agent_compiler.datasource.adapter import (  # noqa: E402
    DatasourceItem,
    DatasourceStructure,
    MCPDatasourceAdapter,
)
from open_agent_compiler.improvement.version import ComponentVersion  # noqa: E402

from personalization import (  # noqa: E402
    builtin_tools,
    build_client_bundle,
    compile_client_fleet,
    elicit_spec,
    make_agent_name_for,
    optimize_client_agent,
    personalize_client,
    serve_personalized_agent,
)
from personalization.client_agent import PERSONALIZED_ROLE  # noqa: E402

CLIENT_ID = "acme"
CLIENT_GOAL = "Answer support tickets from the client's Drive runbooks"
GOAL_MARKER = "Drive runbooks"

_SPEC_JSON = json.dumps({
    "goal": CLIENT_GOAL,
    "preferences": ["Concise, friendly tone"],
    "constraints": ["Never invent a policy that isn't in the runbooks"],
    "example_tasks": [
        {"prompt": "Customer asks about refunds. Runbook folder 'policies'."},
        {"prompt": "Summarize the onboarding steps from the 'setup' folder."},
    ],
    "success_criteria": ["Answers cite the right runbook, within constraints"],
})

CHAT = (
    "Client: Our support runbooks live in Google Drive. I want the agent to read"
    " the right Drive folder and answer tickets from the runbooks — never invent"
    " a policy."
)


# ---- fakes (the only IO seams) -----------------------------------------


class FakeElicitTeacher:
    def complete(self, system, user, *, model=None):
        return _SPEC_JSON


class FakeSessionRunner:
    """Stand-in OpencodeRunner: session output reflects the installed candidate
    prompt (populated by the real make_agent_name_for via flat install)."""

    def __init__(self, project_root):
        self.calls = []
        self.project_root = project_root

    def run(self, *, agent_name, prompt, **kw):
        self.calls.append({"agent": agent_name, "prompt": prompt})
        md = self.project_root / ".opencode" / "agents" / f"{agent_name}.md"
        body = md.read_text(encoding="utf-8") if md.exists() else ""
        return _FakeResult(f"{body}\\n[answering: {prompt}]")


class _FakeResult:
    def __init__(self, text):
        self._text = text
        self.error = None

    def final_text(self):
        return self._text

    def subagent_dispatch_chain(self):
        return []


class FakeJudge:
    def __init__(self):
        self.calls = []

    def judge(self, criteria, target, *, model=None):
        self.calls.append((criteria, str(target)))
        score = 0.95 if GOAL_MARKER in str(target) else 0.2
        return {"pass": score >= 0.7, "score": score, "reasoning": "stub"}


class FakeTeacher:
    def __init__(self):
        self.calls = []

    def rewrite(self, target, guidance, *, context=None, model=None):
        self.calls.append({"target": target, "guidance": guidance})
        return f"{target}\\n\\n{CLIENT_GOAL} — read the right Drive folder per task."

    def complete(self, system, user, *, model=None):
        return _SPEC_JSON


class FakeDriveEnumerator:
    def enumerate(self, *, root):
        return DatasourceStructure(
            root=root,
            items=(
                DatasourceItem(path="/policies", name="policies", is_container=True),
                DatasourceItem(path="/policies/refunds.md", name="refunds.md"),
                DatasourceItem(path="/setup", name="setup", is_container=True),
                DatasourceItem(path="/setup/onboarding.md", name="onboarding.md"),
            ),
        )

    def sample(self, *, n):
        return (
            DatasourceItem(path="/policies/refunds.md", name="refunds.md"),
            DatasourceItem(path="/setup/onboarding.md", name="onboarding.md"),
        )


# ---- fixtures ----------------------------------------------------------


def _mcp_server():
    return ClientMCPServer(
        name="acme_drive", transport="remote",
        url="https://mcp.acme/drive", tools=("drive_search", "drive_read"),
    )


def _datasource():
    return ClientDatasource(
        name="acme_drive_ds", kind="gdrive", mcp_server_name="acme_drive",
    )


def _drive_adapter():
    return MCPDatasourceAdapter(
        name="acme_drive_ds", kind="gdrive",
        enumerator=FakeDriveEnumerator(), mcp_server_name="acme_drive",
    )


# ---- elicitation -------------------------------------------------------


def test_elicit_spec_from_chat():
    spec = elicit_spec(CHAT, FakeElicitTeacher())
    assert spec.goal == CLIENT_GOAL
    assert len(spec.example_tasks) == 2
    assert spec.is_usable


# ---- capability merge + datasource profiling ---------------------------


def test_build_client_bundle_merges_and_profiles():
    bundle, profiles = build_client_bundle(
        CLIENT_ID,
        mcp_servers=(_mcp_server(),),
        datasources=(_datasource(),),
        datasource_adapters={"acme_drive_ds": _drive_adapter()},
    )
    for t in builtin_tools():
        assert t in bundle.builtin_tools
    assert "drive_search" in bundle.client_tool_names()
    assert profiles and profiles[0].leaf_count == 2
    assert bundle.datasource_tool_names(), "no derived datasource tools"
    assert "policies" in profiles[0].top_level_groups


# ---- personalized compile ----------------------------------------------


def test_compile_client_fleet_merges_surface(tmp_path):
    spec = elicit_spec(CHAT, FakeElicitTeacher())
    bundle, profiles = build_client_bundle(
        CLIENT_ID,
        mcp_servers=(_mcp_server(),),
        datasources=(_datasource(),),
        datasource_adapters={"acme_drive_ds": _drive_adapter()},
    )
    compiled = compile_client_fleet(
        CLIENT_ID, spec, bundle,
        datasource_profiles=profiles, target_dir=tmp_path / "acme",
    )
    cfg = json.loads(compiled.opencode_json.read_text())
    assert "acme_drive" in cfg["mcp"]
    assert "drive_search" in cfg["tools"]
    assert "search_corpus" in cfg["tools"]
    assert any(t in cfg["tools"] for t in bundle.datasource_tool_names())
    md = (compiled.agents_dir / f"{PERSONALIZED_ROLE}-primary.md").read_text()
    assert "CLIENT CONTEXT" in md
    assert CLIENT_GOAL in md
    assert "policies" in md


# ---- the full optimization loop (mocked) -------------------------------


def test_optimize_promotes_into_client_bucket(tmp_path):
    spec = elicit_spec(CHAT, FakeElicitTeacher())
    bundle, profiles = build_client_bundle(
        CLIENT_ID,
        mcp_servers=(_mcp_server(),),
        datasources=(_datasource(),),
        datasource_adapters={"acme_drive_ds": _drive_adapter()},
    )
    compiled = compile_client_fleet(
        CLIENT_ID, spec, bundle,
        datasource_profiles=profiles, target_dir=tmp_path / "acme",
    )

    runner = FakeSessionRunner(compiled.project_root)
    judge, teacher = FakeJudge(), FakeTeacher()
    name_for = make_agent_name_for(compiled, model="local/qwen")

    result = optimize_client_agent(
        CLIENT_ID, spec, bundle, compiled,
        runner=runner, judge=judge, teacher=teacher,
        datasource_profiles=profiles, target=0.7, max_rounds=2,
        agent_name_for=name_for,
    )

    assert result.probe_keys == ["example_task:0", "example_task:1"]
    assert runner.calls, "no opencode session was run"
    assert judge.calls and teacher.calls
    assert result.promoted is True
    assert result.winner_score >= 0.7
    promoted_dir = compiled.project_root / ".oac" / "promoted" / CLIENT_ID
    assert promoted_dir.exists()
    promoted_files = list(promoted_dir.glob("*.json"))
    assert promoted_files, "nothing promoted into .oac/promoted/<client_id>/"
    snap = json.loads(promoted_files[0].read_text())
    assert GOAL_MARKER in snap["version"]["definition"]["system_prompt"]


def test_make_agent_name_for_installs_flat_candidate(tmp_path):
    spec = elicit_spec(CHAT, FakeElicitTeacher())
    bundle, _ = build_client_bundle(CLIENT_ID, mcp_servers=(_mcp_server(),))
    compiled = compile_client_fleet(
        CLIENT_ID, spec, bundle, target_dir=tmp_path / "acme",
    )
    name_for = make_agent_name_for(compiled, model="local/qwen")
    version = ComponentVersion.of(
        PERSONALIZED_ROLE, "agent", {"system_prompt": "TUNED PROMPT BODY"},
    )
    name = name_for(version)
    md = compiled.project_root / ".opencode" / "agents" / f"{name}.md"
    assert md.exists(), "flat candidate not installed in project root"
    text = md.read_text()
    assert "TUNED PROMPT BODY" in text
    assert "model: local/qwen" in text


# ---- served agent picks up the promotion -------------------------------


def test_served_agent_applies_client_promotion(tmp_path):
    spec = elicit_spec(CHAT, FakeElicitTeacher())
    bundle, profiles = build_client_bundle(
        CLIENT_ID, mcp_servers=(_mcp_server(),),
        datasources=(_datasource(),),
        datasource_adapters={"acme_drive_ds": _drive_adapter()},
    )
    root = tmp_path / "acme"
    compiled = compile_client_fleet(
        CLIENT_ID, spec, bundle,
        datasource_profiles=profiles, target_dir=root,
    )
    runner = FakeSessionRunner(compiled.project_root)
    optimize_client_agent(
        CLIENT_ID, spec, bundle, compiled,
        runner=runner, judge=FakeJudge(), teacher=FakeTeacher(),
        datasource_profiles=profiles, target=0.7, max_rounds=2,
        agent_name_for=make_agent_name_for(compiled, model="local/qwen"),
    )

    served = serve_personalized_agent(
        CLIENT_ID, spec, bundle,
        datasource_profiles=profiles, target_dir=root,
    )
    assert served["client_id"] == CLIENT_ID
    assert "acme_drive" in served["mcp_servers"]
    assert "drive_search" in served["tools"]
    served_md = (
        root / ".opencode" / "agents" / f"{PERSONALIZED_ROLE}-primary.md"
    ).read_text()
    assert GOAL_MARKER in served_md


# ---- full orchestration (mocked seams) ---------------------------------


def test_personalize_client_end_to_end(tmp_path, monkeypatch):
    from config.settings import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "agents_dir", tmp_path, raising=False)

    def teacher_factory(workspace):
        return FakeTeacher()

    holder = {}

    class RootAwareRunner:
        def __init__(self):
            self.calls = []

        def run(self, *, agent_name, prompt, **kw):
            self.calls.append(agent_name)
            root = holder["root"]
            md = root / ".opencode" / "agents" / f"{agent_name}.md"
            body = md.read_text() if md.exists() else ""
            return _FakeResult(f"{body}\\n[answering: {prompt}]")

    runner = RootAwareRunner()

    from personalization import client_agent

    real_compile = client_agent.compile_client_fleet

    def capture_compile(*a, **k):
        compiled = real_compile(*a, **k)
        holder["root"] = compiled.project_root
        return compiled

    monkeypatch.setattr(client_agent, "compile_client_fleet", capture_compile)
    from personalization import orchestrate
    monkeypatch.setattr(orchestrate, "compile_client_fleet", capture_compile)

    result = personalize_client(
        CLIENT_ID, CHAT,
        mcp_servers=(_mcp_server(),),
        datasources=(_datasource(),),
        datasource_adapters={"acme_drive_ds": _drive_adapter()},
        target=0.7, max_rounds=2,
        elicit_teacher=FakeElicitTeacher(),
        teacher=FakeTeacher(), judge=FakeJudge(), runner=runner,
        teacher_factory=teacher_factory,
    )

    assert result["spec"].goal == CLIENT_GOAL
    assert result["run"] is not None
    assert result["run"].promoted is True
    served = result["served"]
    assert "acme_drive" in served["mcp_servers"]
    served_md = (
        holder["root"] / ".opencode" / "agents"
        / f"{PERSONALIZED_ROLE}-primary.md"
    ).read_text()
    assert GOAL_MARKER in served_md


def test_personalize_client_compile_only(tmp_path, monkeypatch):
    from config.settings import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "agents_dir", tmp_path, raising=False)

    result = personalize_client(
        CLIENT_ID, CHAT,
        mcp_servers=(_mcp_server(),),
        optimize=False,
        elicit_teacher=FakeElicitTeacher(),
    )
    assert result["run"] is None
    assert "acme_drive" in result["served"]["mcp_servers"]
    assert "drive_search" in result["served"]["tools"]


def test_unusable_spec_rejected():
    class EmptyTeacher:
        def complete(self, system, user, *, model=None):
            return json.dumps({"goal": "do stuff"})

    with pytest.raises(Exception):
        elicit_spec(CHAT, EmptyTeacher(), require_usable=True)
'''


_ADAPTABILITY_TESTS_TEMPLATE = '''"""Adaptability suite — the per-client structure ADAPTS per client (MOCKED).

The platform's moat: ONE base fleet, driven by DIFFERENT clients, yields
DIFFERENT personalized agents. This test proves it with TWO sharply distinct
mocked personas pushed through the generated personalization pipeline with NO
live opencode/qwen/z.ai/network — every IO seam is a fake.

For each persona we assert ADAPTATION (its own merged tool surface + its own
compiled prompt) and then the keystone: the SAME base fleet yields a DIFFERENT,
persona-shaped promoted winner per persona. Ships GREEN out of the box:
`uv run pytest tests/test_adaptability.py`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

os.environ.setdefault("ZAI_API_KEY", "test-key")

import pytest  # noqa: E402

from open_agent_compiler import ClientDatasource, ClientMCPServer  # noqa: E402
from open_agent_compiler.datasource.adapter import (  # noqa: E402
    DatasourceItem,
    DatasourceStructure,
    MCPDatasourceAdapter,
)
from open_agent_compiler.improvement.version import ComponentVersion  # noqa: E402

from personalization import (  # noqa: E402
    build_client_bundle,
    builtin_tools,
    compile_client_fleet,
    elicit_spec,
    make_agent_name_for,
    optimize_client_agent,
)
from personalization.client_agent import PERSONALIZED_ROLE  # noqa: E402


# ---- persona = a complete, self-contained mocked client ----------------


@dataclass(frozen=True)
class Persona:
    client_id: str
    goal: str
    tone_keyword: str
    pref: str
    mcp_name: str
    mcp_tools: tuple
    ds_name: str
    ds_kind: str
    ds_items: tuple
    ds_marker: str

    def spec_json(self) -> str:
        return json.dumps({
            "goal": self.goal,
            "preferences": [self.pref],
            "constraints": ["Stay within the client's stated scope"],
            "example_tasks": [
                {"prompt": f"{self.client_id} task one for {self.tone_keyword} output."},
                {"prompt": f"{self.client_id} task two."},
            ],
            "success_criteria": [f"Output is {self.tone_keyword} and on-task"],
        })


PERSONA_A = Persona(
    client_id="shopfast",
    goal="Write punchy short-form launch ad copy",
    tone_keyword="punchy",
    pref="Punchy, short, emoji-light copy",
    mcp_name="shopify",
    mcp_tools=("list_products", "get_orders"),
    ds_name="shopfast_photos",
    ds_kind="gdrive",
    ds_items=(
        DatasourceItem(path="/Photos/2024-03", name="2024-03", is_container=True),
        DatasourceItem(path="/Photos/2024-03/2024-03-01_aero.jpg", name="2024-03-01_aero.jpg"),
        DatasourceItem(path="/Photos/2024-04/2024-04-10_drop.jpg", name="2024-04-10_drop.jpg"),
    ),
    ds_marker="2024-03",
)

PERSONA_B = Persona(
    client_id="datacore",
    goal="Explain product features formally from warehouse data",
    tone_keyword="formal",
    pref="Formal, technical, no-hype tone",
    mcp_name="analytics",
    mcp_tools=("run_query",),
    ds_name="datacore_warehouse",
    ds_kind="postgres",
    ds_items=(
        DatasourceItem(path="public/fct_events", name="fct_events", is_container=True, item_type="table"),
        DatasourceItem(path="public/fct_events/user_id", name="user_id", item_type="column"),
        DatasourceItem(path="public/dim_users/plan_tier", name="plan_tier", item_type="column"),
    ),
    ds_marker="fct_events",
)

ALL_PERSONAS = [PERSONA_A, PERSONA_B]
PERSONA_IDS = [p.client_id for p in ALL_PERSONAS]


# ---- fakes (the only IO seams) -----------------------------------------


class FakeElicitTeacher:
    def __init__(self, persona):
        self.persona = persona

    def complete(self, system, user, *, model=None):
        return self.persona.spec_json()


class PersonaEnumerator:
    def __init__(self, persona):
        self.persona = persona

    def enumerate(self, *, root):
        return DatasourceStructure(root=root, items=self.persona.ds_items)

    def sample(self, *, n):
        leaves = tuple(i for i in self.persona.ds_items if not i.is_container)
        return leaves[:n]


class FakeSessionRunner:
    """Session output reflects the installed candidate prompt (flat install)."""

    def __init__(self, project_root):
        self.calls = []
        self.project_root = project_root

    def run(self, *, agent_name, prompt, **kw):
        self.calls.append(agent_name)
        md = self.project_root / ".opencode" / "agents" / f"{agent_name}.md"
        body = md.read_text(encoding="utf-8") if md.exists() else ""
        return _FakeResult(f"{body}\\n[answering: {prompt}]")


class _FakeResult:
    def __init__(self, text):
        self._text = text
        self.error = None

    def final_text(self):
        return self._text

    def subagent_dispatch_chain(self):
        return []


class PersonaJudge:
    """High only when the candidate prose carries THIS persona's tone keyword."""

    def __init__(self, persona):
        self.persona = persona
        self.calls = []

    def judge(self, criteria, target, *, model=None):
        self.calls.append(str(target))
        score = 0.95 if self.persona.tone_keyword in str(target) else 0.2
        return {"pass": score >= 0.7, "score": score, "reasoning": "stub"}


class PersonaTeacher:
    """Rewrite incorporates THIS persona's tone keyword (so it wins)."""

    def __init__(self, persona):
        self.persona = persona
        self.calls = []

    def rewrite(self, target, guidance, *, context=None, model=None):
        self.calls.append(guidance)
        return f"{target}\\n\\n{self.persona.goal} — keep it {self.persona.tone_keyword}."


# ---- the per-persona pipeline driver -----------------------------------


def _adapter(persona):
    return MCPDatasourceAdapter(
        name=persona.ds_name, kind=persona.ds_kind,
        enumerator=PersonaEnumerator(persona), mcp_server_name=persona.mcp_name,
    )


def _drive(persona, root):
    """chat -> spec -> merge+profile -> compile, returning (spec, bundle, compiled)."""
    spec = elicit_spec("chat", FakeElicitTeacher(persona))
    server = ClientMCPServer(
        name=persona.mcp_name, transport="remote",
        url=f"https://mcp.{persona.client_id}/x", tools=persona.mcp_tools,
    )
    ds = ClientDatasource(
        name=persona.ds_name, kind=persona.ds_kind, mcp_server_name=persona.mcp_name,
    )
    bundle, profiles = build_client_bundle(
        persona.client_id,
        mcp_servers=(server,), datasources=(ds,),
        datasource_adapters={persona.ds_name: _adapter(persona)},
    )
    compiled = compile_client_fleet(
        persona.client_id, spec, bundle,
        datasource_profiles=profiles, target_dir=root,
    )
    return spec, bundle, compiled


def _run_autoloop(persona, root):
    spec, bundle, compiled = _drive(persona, root)
    runner = FakeSessionRunner(compiled.project_root)
    result = optimize_client_agent(
        persona.client_id, spec, bundle, compiled,
        runner=runner, judge=PersonaJudge(persona), teacher=PersonaTeacher(persona),
        target=0.7, max_rounds=2,
        agent_name_for=make_agent_name_for(compiled, model="local/qwen"),
    )
    return spec, bundle, compiled, result, runner


# ---- per-persona ADAPTATION --------------------------------------------


@pytest.mark.parametrize("persona", ALL_PERSONAS, ids=PERSONA_IDS)
def test_merged_surface_adapts_to_persona(persona, tmp_path):
    _, bundle, compiled = _drive(persona, tmp_path / persona.client_id)
    cfg = json.loads(compiled.opencode_json.read_text())
    tools = set(cfg["tools"])
    for t in builtin_tools():
        assert t in tools
    for t in persona.mcp_tools:
        assert t in tools
    assert persona.mcp_name in cfg["mcp"]
    assert bundle.datasource_tool_names()


@pytest.mark.parametrize("persona", ALL_PERSONAS, ids=PERSONA_IDS)
def test_compiled_prompt_adapts_to_persona(persona, tmp_path):
    _, _, compiled = _drive(persona, tmp_path / persona.client_id)
    md = (compiled.agents_dir / f"{PERSONALIZED_ROLE}-primary.md").read_text()
    assert persona.goal in md
    assert persona.pref in md
    assert persona.ds_marker in md  # the persona's OWN data layout


# ---- cross-persona DISTINCTNESS + NO LEAKAGE ---------------------------


def test_personas_compile_to_distinct_surfaces(tmp_path):
    a_spec, a_bundle, a_compiled = _drive(PERSONA_A, tmp_path / "a")
    b_spec, b_bundle, b_compiled = _drive(PERSONA_B, tmp_path / "b")
    a_cfg = json.loads(a_compiled.opencode_json.read_text())
    b_cfg = json.loads(b_compiled.opencode_json.read_text())
    sa, sb = set(a_cfg["tools"]), set(b_cfg["tools"])
    # each persona's own tools present, and not the other's
    assert "list_products" in sa and "list_products" not in sb
    assert "run_query" in sb and "run_query" not in sa
    assert sa != sb
    # prompts differ + carry only their own tone keyword
    a_md = (a_compiled.agents_dir / f"{PERSONALIZED_ROLE}-primary.md").read_text()
    b_md = (b_compiled.agents_dir / f"{PERSONALIZED_ROLE}-primary.md").read_text()
    assert a_md != b_md
    assert "punchy" in a_md and "punchy" not in b_md
    assert "formal" in b_md and "formal" not in a_md


# ---- the AUTORUN adapts: SAME base fleet -> different promoted winners --


@pytest.mark.parametrize("persona", ALL_PERSONAS, ids=PERSONA_IDS)
def test_autorun_promotes_persona_shaped_winner(persona, tmp_path):
    _, _, compiled, result, runner = _run_autoloop(persona, tmp_path / persona.client_id)
    assert runner.calls
    assert result.promoted is True
    assert result.winner_score >= 0.7
    promoted_dir = compiled.project_root / ".oac" / "promoted" / persona.client_id
    assert promoted_dir.exists()
    files = list(promoted_dir.glob("*.json"))
    assert files
    snap = json.loads(files[0].read_text())
    prompt = snap["version"]["definition"]["system_prompt"]
    assert persona.tone_keyword in prompt
    for other in ALL_PERSONAS:
        if other.client_id != persona.client_id:
            assert other.tone_keyword not in prompt


def test_same_base_fleet_adapts_differently_per_persona(tmp_path):
    """THE moat: identical base fleet, different persona -> different agent."""
    winners = {}
    for persona in ALL_PERSONAS:
        _, _, compiled, result, _ = _run_autoloop(persona, tmp_path / persona.client_id)
        assert result.promoted is True
        promoted_dir = compiled.project_root / ".oac" / "promoted" / persona.client_id
        snap = json.loads(next(promoted_dir.glob("*.json")).read_text())
        winners[persona.client_id] = snap["version"]["definition"]["system_prompt"]
    assert len(set(winners.values())) == len(ALL_PERSONAS)
    for persona in ALL_PERSONAS:
        assert persona.tone_keyword in winners[persona.client_id]
'''


_FLEET_REGISTRY_TEMPLATE = '''"""Base agent fleet for {{project_name}} (the saas-personalized template).

A small but real fleet (planner / worker / critic). This is the platform's BASE
agent set — every client inherits it, and the per-client personalization module
(`personalization/`) blends each client's own MCP tools + datasources on top and
auto-optimizes a private copy tuned to the client's workflow.

Two entry points:
  * `build_fleet_registry(model_name=...)` + `ROLES` — what `compile_personalized`
    compiles against (the per-client factory).
  * `registry()` — the no-arg factory `oac compile / test / improve` resolve via
    `agents:registry`.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    AgentToolPermissions as ToolPermissions,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "{{default_model}}"

# The base roles every client inherits. `planner` is the entry/anchor role the
# per-client loop tunes first (see personalization.client_agent.PERSONALIZED_ROLE).
ROLES = ("planner", "worker", "critic")

_PROMPTS = {
    "planner": (
        "You are the planner for {{project_name}}. Break the user's request into"
        " a short ordered plan, decide WHICH tools to use and in what sequence,"
        " and hand each step to the worker. Prefer the client's own datasources"
        " when the task references their data."
    ),
    "worker": (
        "You are the worker. Execute one planned step at a time using the"
        " allowed tools. Call the client's tools/datasources when the step needs"
        " their private data; otherwise use the platform's built-in tools."
    ),
    "critic": (
        "You are the critic. Check the worker's output against the user's intent"
        " and any stated constraints. If it falls short, say precisely what to"
        " fix; otherwise approve."
    ),
}


def build_fleet_registry(*, model_name: str = DEFAULT_MODEL) -> AgentRegistry:
    """One registry hosting all base roles. The per-client compile overlays the
    client's spec-derived prompt + merged tool surface on top of this."""
    reg = AgentRegistry()
    params = ModelParameters(model_name=model_name, temperature=0.7)

    slots: list[TemplateSlot] = []
    first_agent_id: str | None = None
    for role in ROLES:
        agent_def = AgentDefinition(
            header=AgentHeader(
                agent_id=role, name=role,
                description=f"{role} agent in the {{project_name}} fleet",
            ),
            usage_explanation_long=f"The {role} role in the base fleet.",
            usage_explanation_short=f"{role} role",
            system_prompt=_PROMPTS[role],
            tool_permissions=ToolPermissions(),
        )
        # register_with_improvements auto-merges any promoted snapshot under
        # .oac/promoted/ (per-client buckets included on a per-client compile).
        agent_id = reg.register_with_improvements(
            role, agent_def, params, project_root=PROJECT_ROOT,
        )
        if first_agent_id is None:
            first_agent_id = agent_id
        slots.append(
            TemplateSlot(name=role, default_agent_id=agent_id,
                         also_compile_as_primary=True)
        )

    # A 'primary' slot is required; alias it to the planner (entry role).
    slots.insert(0, TemplateSlot(name="primary", default_agent_id=first_agent_id))
    reg.register_template(TemplateTree(name="default", slots=slots))
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="default"),
    )
    return reg


def registry() -> AgentRegistry:
    """No-arg factory resolved by `oac compile / test / improve`."""
    return build_fleet_registry()


__all__ = ["ROLES", "build_fleet_registry", "registry", "DEFAULT_MODEL"]
'''
