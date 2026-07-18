"""Adaptability suite — the per-client structure ADAPTS to differing clients.

The platform's moat is that ONE base SaaS fleet, driven by N different clients,
yields N genuinely different personalized agents AND N different autoruns. This
suite proves that with THREE sharply distinct mocked client personas pushed
through the WHOLE per-client pipeline with NO live opencode/qwen/z.ai/network:

  chat transcript  -> elicit ClientSpec (teacher echoes the persona's prefs)
    -> merge built-ins ∪ persona MCP tools ∪ persona datasource-derived tools
    -> auto-profile the persona datasource (mock MCPEnumerator -> its layout)
    -> compile_personalized (persona overlay + merged surface + datasource ctx)
    -> seed probes from the persona's example_tasks
    -> build the client rubric/criterion from the persona's success_criteria
    -> PersonalizationRun: a mocked teacher whose rewrite carries the persona's
       TONE keyword, a judge scoring against the persona's marker, a mock runner
    -> promotion into .oac/promoted/<client_id>/

We assert THREE things per persona — adaptation, distinctness, isolation — and
then assert the SAME baseline yields different promoted agents per persona.

Personas:
  A "shopfast"  — e-commerce ad client: punchy/short/emoji-light copy; Shopify
                  MCP (list_products/get_orders); Drive of dated product photos;
                  success = hook strength / CTA clarity.
  B "datacore"  — B2B SaaS client: formal/technical/no-hype; analytics MCP
                  (run_query); Postgres schema-style datasource; success =
                  factual accuracy / feature framing.
  C "cornerfix" — local-services client: warm/regional/plain-language; calendar
                  MCP (create_event/list_slots); small flat datasource; success
                  = locality / booking CTA.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from open_agent_compiler.datasource.adapter import (
    DatasourceItem,
    DatasourceStructure,
    MCPDatasourceAdapter,
)
from open_agent_compiler.datasource.profile import profile_datasource
from open_agent_compiler.datasource.tools import apply_profile_to_datasource
from open_agent_compiler.improvement.mutators import (
    LLMPromptRewriter,
    ToolSelectionMutator,
    ToolSequenceMutator,
)
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.capability_bundle import (
    ClientCapabilityBundle,
    ClientDatasource,
    ClientMCPServer,
    merge_capabilities,
)
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.personalization.compile import compile_personalized
from open_agent_compiler.personalization.elicit import elicit_client_spec
from open_agent_compiler.personalization.judge import build_client_rubric
from open_agent_compiler.personalization.probes import seed_probes_from_spec, spec_probe_keys
from open_agent_compiler.personalization.run import PersonalizationRun, build_joint_mutators
from open_agent_compiler.personalization.spec import ClientSpec, ExampleTask


# ===========================================================================
# Persona definition — a complete, self-contained mocked client.
# ===========================================================================


@dataclass(frozen=True)
class Persona:
    """One mocked client: chat + prefs + tools + data + success + autorun signal."""

    client_id: str
    chat_transcript: str
    # what the elicitation teacher should echo back as the spec (mock target):
    goal: str
    tone_keyword: str  # the distinctive tone word; must end up in the spec + winner
    preferences: tuple[str, ...]
    constraints: tuple[str, ...]
    example_tasks: tuple[ExampleTask, ...]
    success_criteria: tuple[str, ...]
    # capability surface:
    mcp_server: ClientMCPServer
    datasource: ClientDatasource
    ds_structure: DatasourceStructure
    ds_sample: tuple[DatasourceItem, ...]
    # a fingerprint string that must appear in the datasource layout summary:
    ds_layout_marker: str

    def spec_payload(self) -> dict:
        """The JSON the (mocked) elicitation teacher returns for this persona."""
        return {
            "goal": self.goal,
            "preferences": list(self.preferences),
            "constraints": list(self.constraints),
            "example_tasks": [
                {"prompt": t.prompt, "expected_outcome": t.expected_outcome}
                for t in self.example_tasks
            ],
            "success_criteria": list(self.success_criteria),
        }

    def all_tool_names(self) -> set[str]:
        """Every persona-specific tool name (MCP + datasource-derived)."""
        return set(self.mcp_server.tools)


# ---- the three personas ---------------------------------------------------


def _persona_a() -> Persona:
    return Persona(
        client_id="shopfast",
        chat_transcript=(
            "Client: We sell sneakers on Shopify. I want punchy, short ad copy"
            " for product launches — keep it snappy and emoji-light. Pull live"
            " products and recent orders, and use our product photos."
        ),
        goal="Write punchy short-form launch ad copy for Shopify products",
        tone_keyword="punchy",
        preferences=("Punchy, short, emoji-light copy", "Lead with the hook"),
        constraints=("Never invent a discount that is not live",),
        example_tasks=(
            ExampleTask(
                prompt="Write a launch ad for the new Aero running shoe.",
                expected_outcome="A short punchy hook + a clear CTA.",
            ),
            ExampleTask(prompt="Spin a 1-line teaser for our spring drop."),
        ),
        success_criteria=(
            "The hook is strong in the first line",
            "The CTA is clear and singular",
        ),
        mcp_server=ClientMCPServer(
            name="shopify",
            transport="remote",
            url="https://mcp.shopfast/shopify",
            tools=("list_products", "get_orders"),
        ),
        datasource=ClientDatasource(
            name="shopfast_photos", kind="gdrive", mcp_server_name="shopify",
        ),
        ds_structure=DatasourceStructure(
            root="/Photos",
            items=(
                DatasourceItem(path="/Photos/2024-03", name="2024-03", is_container=True),
                DatasourceItem(path="/Photos/2024-03/2024-03-01_aero.jpg", name="2024-03-01_aero.jpg"),
                DatasourceItem(path="/Photos/2024-03/2024-03-02_spring.jpg", name="2024-03-02_spring.jpg"),
                DatasourceItem(path="/Photos/2024-04", name="2024-04", is_container=True),
                DatasourceItem(path="/Photos/2024-04/2024-04-10_drop.jpg", name="2024-04-10_drop.jpg"),
            ),
        ),
        ds_sample=(
            DatasourceItem(path="/Photos/2024-03/2024-03-01_aero.jpg", name="2024-03-01_aero.jpg"),
            DatasourceItem(path="/Photos/2024-04/2024-04-10_drop.jpg", name="2024-04-10_drop.jpg"),
        ),
        ds_layout_marker="2024-03",  # dated folder structure shows up
    )


def _persona_b() -> Persona:
    return Persona(
        client_id="datacore",
        chat_transcript=(
            "Client: We're a B2B analytics SaaS. I need formal, technical,"
            " no-hype feature explanations grounded in our metrics. Query our"
            " warehouse and frame features factually against the data."
        ),
        goal="Explain product features formally and factually from warehouse data",
        tone_keyword="formal",
        preferences=("Formal, technical, no-hype tone", "Cite the metric"),
        constraints=("Never overstate a benefit without data",),
        example_tasks=(
            ExampleTask(
                prompt="Explain our cohort-retention feature to a CTO.",
                expected_outcome="A factual, technical explanation tied to metrics.",
            ),
            ExampleTask(prompt="Frame our anomaly-detection feature for a data team."),
        ),
        success_criteria=(
            "Claims are factually accurate and grounded in the data",
            "Feature framing is technical, not hype",
        ),
        mcp_server=ClientMCPServer(
            name="analytics",
            transport="remote",
            url="https://mcp.datacore/analytics",
            tools=("run_query",),
        ),
        datasource=ClientDatasource(
            name="datacore_warehouse", kind="postgres",
            mcp_server_name="analytics",
        ),
        ds_structure=DatasourceStructure(
            root="public",
            items=(
                DatasourceItem(path="public/fct_events", name="fct_events", is_container=True, item_type="table"),
                DatasourceItem(path="public/fct_events/user_id", name="user_id", item_type="column"),
                DatasourceItem(path="public/fct_events/event_ts", name="event_ts", item_type="column"),
                DatasourceItem(path="public/dim_users", name="dim_users", is_container=True, item_type="table"),
                DatasourceItem(path="public/dim_users/plan_tier", name="plan_tier", item_type="column"),
            ),
        ),
        ds_sample=(
            DatasourceItem(path="public/fct_events/user_id", name="user_id", item_type="column"),
            DatasourceItem(path="public/dim_users/plan_tier", name="plan_tier", item_type="column"),
        ),
        ds_layout_marker="fct_events",  # schema-style table names show up
    )


def _persona_c() -> Persona:
    return Persona(
        client_id="cornerfix",
        chat_transcript=(
            "Client: We're a local plumbing service in Leeds. I want warm,"
            " regional, plain-language replies that always nudge customers to"
            " book a slot. Check the calendar for openings."
        ),
        goal="Reply warmly and book local plumbing jobs from calendar slots",
        tone_keyword="warm",
        preferences=("Warm, regional, plain-language tone", "Mention the local area"),
        constraints=("Never quote a fixed price before a visit",),
        example_tasks=(
            ExampleTask(
                prompt="Customer in Leeds has a leaking tap. Reply and book them in.",
                expected_outcome="A warm, local reply ending in a booking CTA.",
            ),
            ExampleTask(prompt="Someone asks if we cover the LS6 postcode."),
        ),
        success_criteria=(
            "The reply references the customer's local area",
            "The reply ends with a clear booking CTA",
        ),
        mcp_server=ClientMCPServer(
            name="calendar",
            transport="remote",
            url="https://mcp.cornerfix/calendar",
            tools=("list_slots", "create_event"),
        ),
        datasource=ClientDatasource(
            name="cornerfix_notes", kind="fs", mcp_server_name="calendar",
        ),
        ds_structure=DatasourceStructure(
            root="/notes",
            items=(
                DatasourceItem(path="/notes/areas.txt", name="areas.txt"),
                DatasourceItem(path="/notes/pricing.txt", name="pricing.txt"),
                DatasourceItem(path="/notes/faq.txt", name="faq.txt"),
            ),
        ),
        ds_sample=(
            DatasourceItem(path="/notes/areas.txt", name="areas.txt"),
            DatasourceItem(path="/notes/faq.txt", name="faq.txt"),
        ),
        ds_layout_marker="areas.txt",  # small flat file list shows up
    )


ALL_PERSONAS = [_persona_a(), _persona_b(), _persona_c()]
PERSONA_IDS = [p.client_id for p in ALL_PERSONAS]


# ===========================================================================
# Mock IO seams (the only IO; mirrors tests/personalization/test_run.py).
# ===========================================================================


class FakeElicitTeacher:
    """Elicitation teacher: echoes a persona's stated prefs into the spec JSON."""

    def __init__(self, persona: Persona) -> None:
        self.persona = persona
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        self.calls.append((system, user))
        return json.dumps(self.persona.spec_payload())


class PersonaEnumerator:
    """Mock MCPEnumerator returning THIS persona's canned datasource structure."""

    def __init__(self, persona: Persona) -> None:
        self.persona = persona

    def enumerate(self, *, root: str) -> DatasourceStructure:
        return self.persona.ds_structure

    def sample(self, *, n: int) -> tuple[DatasourceItem, ...]:
        return self.persona.ds_sample[:n]


class FakeSessionRunner:
    """Stand-in OpencodeRunner: session output = the installed candidate prompt."""

    def __init__(self, installed: dict[str, str]) -> None:
        self.calls: list[dict] = []
        self.installed = installed

    def run(self, *, agent_name: str, prompt: str, **kw):
        self.calls.append({"agent": agent_name, "prompt": prompt})
        system = self.installed.get(agent_name, "")
        return _FakeResult(f"{system}\n[answering: {prompt}]")


class _FakeResult:
    def __init__(self, text: str) -> None:
        self._text = text
        self.error = None

    def final_text(self) -> str:
        return self._text

    def subagent_dispatch_chain(self):
        return []


class PersonaJudge:
    """Scores high only when the winning prose carries THIS persona's tone keyword.

    This is what makes the autorun ADAPT: a candidate that does not realise the
    persona's tone never clears the bar, so the promoted winner is persona-shaped.
    """

    def __init__(self, persona: Persona) -> None:
        self.persona = persona
        self.calls: list[tuple[str, str]] = []

    def judge(self, criteria, target, *, model=None):
        self.calls.append((str(criteria), str(target)))
        hit = self.persona.tone_keyword in str(target)
        score = 0.95 if hit else 0.2
        return {"pass": score >= 0.7, "score": score, "reasoning": "stub"}


class PersonaTeacher:
    """Rewriter teacher: its rewrite INCORPORATES this persona's tone keyword.

    Mirrors a real teacher reading the persona's guidance/failures and rewriting
    the prompt toward the persona's tone — here, deterministically, by stating
    the persona goal + tone so the judge scores it as the winner.
    """

    def __init__(self, persona: Persona) -> None:
        self.persona = persona
        self.calls: list[dict] = []

    def rewrite(self, target, guidance, *, context=None, model=None):
        self.calls.append({"target": target, "guidance": guidance})
        return (
            f"{target}\n\n{self.persona.goal} — keep every reply"
            f" {self.persona.tone_keyword}."
        )


# ===========================================================================
# Shared fixtures: the ONE base SaaS fleet every persona personalizes.
# ===========================================================================

BASE_PROMPT = "You are a generic assistant."  # carries NO persona signal


def _base_factory():
    """The single base SaaS fleet factory — identical for every persona."""
    reg = AgentRegistry()
    a = AgentDefinition(
        header=AgentHeader(agent_id="writer", name="writer-bot", description="d"),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt=BASE_PROMPT,
    )
    aid = reg.register_agent(
        "primary", a, ModelParameters(model_name="local/qwen", temperature=0.7)
    )
    reg.register_template(
        TemplateTree(name="tpl", slots=[TemplateSlot(name="primary", default_agent_id=aid)])
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
    return reg


def _preset():
    return ModelPreset(
        name="p", provider="vllm", model_id="x",
        sampling=SamplingDefaults(temperature=0.0),
    )


def _builtin_tools() -> tuple[str, ...]:
    """The platform's built-in surface — shared across every persona."""
    return ("search_corpus", "summarize", "export_report")


# ---- the per-persona pipeline driver --------------------------------------


@dataclass
class CompiledPersona:
    """Everything one persona's pipeline produced, for assertions."""

    persona: Persona
    spec: ClientSpec
    bundle: ClientCapabilityBundle
    surface_allow_list: tuple[str, ...]
    profile_summary: str
    compiled: object  # PersonalizedCompile
    opencode_cfg: dict
    agent_md: str
    probe_keys: list[str]
    rubric: str


def _drive_persona(persona: Persona, project_root: Path) -> CompiledPersona:
    """Run one persona through chat->spec->merge->profile->compile->probes->rubric."""
    # 1) elicit the spec via the (mocked) teacher that echoes persona prefs.
    elicit_teacher = FakeElicitTeacher(persona)
    spec = elicit_client_spec(
        persona.chat_transcript, elicit_teacher, require_usable=True,
    )

    # 2) auto-profile the persona datasource via its mock enumerator.
    adapter = MCPDatasourceAdapter(
        name=persona.datasource.name, kind=persona.datasource.kind,
        enumerator=PersonaEnumerator(persona),
        mcp_server_name=persona.mcp_server.name,
    )
    profile = profile_datasource(adapter)
    enriched_ds = apply_profile_to_datasource(persona.datasource, profile)

    # 3) merge built-ins ∪ persona MCP tools ∪ datasource-derived tools.
    bundle = ClientCapabilityBundle(
        client_id=persona.client_id,
        builtin_tools=_builtin_tools(),
        mcp_servers=(persona.mcp_server,),
        datasources=(enriched_ds,),
    )
    surface = merge_capabilities(bundle)

    # 4) personalized compile: overlay + merged surface + datasource context.
    compiled = compile_personalized(
        persona.client_id, spec, bundle, project_root,
        factory=_base_factory, config="prod", preset=_preset(),
        datasource_profiles=(profile,),
    )
    cfg = json.loads(compiled.opencode_json.read_text())
    agent_md = (compiled.agents_dir / "primary.md").read_text()

    # 5) probes + rubric.
    seed_probes_from_spec(spec, project_root / ".oac" / persona.client_id / "probes.json")
    keys = spec_probe_keys(spec)
    rubric = build_client_rubric(spec)

    return CompiledPersona(
        persona=persona, spec=spec, bundle=bundle,
        surface_allow_list=surface.allow_list,
        profile_summary=profile.summary,
        compiled=compiled, opencode_cfg=cfg, agent_md=agent_md,
        probe_keys=keys, rubric=rubric,
    )


# ===========================================================================
# Deliverable 1 — per-persona ADAPTATION.
# ===========================================================================


@pytest.mark.parametrize("persona", ALL_PERSONAS, ids=PERSONA_IDS)
def test_elicited_spec_reflects_persona(persona: Persona, tmp_path: Path):
    """The elicited ClientSpec carries THIS persona's goal/prefs/tone + request."""
    teacher = FakeElicitTeacher(persona)
    spec = elicit_client_spec(persona.chat_transcript, teacher, require_usable=True)

    assert spec.goal == persona.goal
    # the persona's stated preferences are echoed into the spec
    assert any(persona.tone_keyword in p.lower() for p in spec.preferences)
    # the example tasks are the persona's OWN tasks (the custom chat request)
    assert spec.example_tasks == persona.example_tasks
    assert spec.success_criteria == persona.success_criteria
    # the teacher actually saw the persona's chat transcript
    assert teacher.calls and persona.chat_transcript.strip()[:20] in teacher.calls[0][1]


@pytest.mark.parametrize("persona", ALL_PERSONAS, ids=PERSONA_IDS)
def test_merged_surface_carries_persona_tools(persona: Persona, tmp_path: Path):
    """The merged capability surface holds THIS persona's MCP + datasource tools."""
    cp = _drive_persona(persona, tmp_path / persona.client_id)
    allow = set(cp.surface_allow_list)

    # built-ins are present for everyone
    for t in _builtin_tools():
        assert t in allow
    # this persona's MCP tools are present
    for t in persona.mcp_server.tools:
        assert t in allow, f"{persona.client_id} missing its MCP tool {t}"
    # datasource-derived tools (search_<ds>/read_<ds>_by_path) are present
    derived = cp.bundle.datasource_tool_names()
    assert derived, f"{persona.client_id} produced no datasource tools"
    for t in derived:
        assert t in allow
    # the persona's MCP server is wired into opencode.json
    assert persona.mcp_server.name in cp.opencode_cfg["mcp"]


@pytest.mark.parametrize("persona", ALL_PERSONAS, ids=PERSONA_IDS)
def test_compiled_prompt_carries_goal_prefs_and_layout(persona: Persona, tmp_path: Path):
    """The compiled prompt carries the persona's goal/prefs AND its data layout."""
    cp = _drive_persona(persona, tmp_path / persona.client_id)
    md = cp.agent_md

    # base prompt preserved
    assert BASE_PROMPT in md
    # persona goal + tone preference injected via the client overlay
    assert persona.goal in md
    assert any(pref in md for pref in persona.preferences)
    assert persona.constraints[0] in md
    # datasource layout summary injected (the persona's OWN structure)
    assert persona.ds_layout_marker in md, (
        f"{persona.client_id} datasource layout {persona.ds_layout_marker!r}"
        " not in compiled prompt"
    )


@pytest.mark.parametrize("persona", ALL_PERSONAS, ids=PERSONA_IDS)
def test_probes_and_rubric_seeded_from_persona(persona: Persona, tmp_path: Path):
    """Probes come from the persona's example_tasks; rubric from its criteria."""
    cp = _drive_persona(persona, tmp_path / persona.client_id)

    assert cp.probe_keys == [f"example_task:{i}" for i in range(len(persona.example_tasks))]
    probes_file = (
        tmp_path / persona.client_id / ".oac" / persona.client_id / "probes.json"
    )
    assert probes_file.exists()
    seeded = json.loads(probes_file.read_text())
    # the persona's first example-task prompt is the literal probe text
    first = persona.example_tasks[0].prompt
    assert any(first in v for v in seeded.values())
    # the judge rubric carries THIS persona's success criteria
    for crit in persona.success_criteria:
        assert crit in cp.rubric


# ===========================================================================
# Deliverable 1 — cross-persona DISTINCTNESS + NO LEAKAGE.
# ===========================================================================


def test_personas_compile_to_distinct_agents(tmp_path: Path):
    """Three personas -> three different prompts + tool surfaces, traceable to inputs."""
    compiled = {
        p.client_id: _drive_persona(p, tmp_path / p.client_id) for p in ALL_PERSONAS
    }
    a, b, c = (compiled[k] for k in ("shopfast", "datacore", "cornerfix"))

    # --- prompts differ, and differ from the (persona-free) baseline ---
    prompts = {a.agent_md, b.agent_md, c.agent_md, BASE_PROMPT}
    assert len(prompts) == 4, "compiled prompts are not all distinct"
    assert "punchy" in a.agent_md and "punchy" not in b.agent_md
    assert "formal" in b.agent_md and "formal" not in a.agent_md
    assert "warm" in c.agent_md and "warm" not in a.agent_md

    # --- tool surfaces differ, traceable to each persona's connected tools ---
    sa, sb, sc = set(a.surface_allow_list), set(b.surface_allow_list), set(c.surface_allow_list)
    assert "list_products" in sa and "run_query" in sb and "list_slots" in sc
    assert sa != sb and sb != sc and sa != sc

    # --- NO LEAKAGE: one persona's tools never appear in another's surface ---
    for src_id, src_set in (("shopfast", sa), ("datacore", sb), ("cornerfix", sc)):
        for other in ALL_PERSONAS:
            if other.client_id == src_id:
                continue
            leaked = src_set & other.all_tool_names()
            assert not leaked, (
                f"{src_id}'s surface leaked {leaked} from {other.client_id}"
            )

    # --- datasource layouts differ (each carries its own fingerprint) ---
    assert a.persona.ds_layout_marker in a.profile_summary
    assert a.persona.ds_layout_marker not in b.profile_summary
    assert b.persona.ds_layout_marker in b.profile_summary
    assert c.persona.ds_layout_marker in c.profile_summary


def test_joint_mutators_adapt_to_each_persona(tmp_path: Path):
    """The joint mutation space wires in EACH persona's own tool names (no leak)."""
    for persona in ALL_PERSONAS:
        cp = _drive_persona(persona, tmp_path / persona.client_id)
        client_tools = cp.bundle.client_tool_names()
        mutators = build_joint_mutators(
            cp.spec, client_tool_names=client_tools,
        )
        # prompt+workflow rewriter guidance is derived from THIS persona's goal
        rw = next(m for m in mutators if isinstance(m, LLMPromptRewriter))
        assert persona.goal in rw.guidance
        assert persona.preferences[0] in rw.guidance
        # tool-selection/sequence mutators target this persona's own tools
        enabled = {
            m.tool_name for m in mutators
            if isinstance(m, ToolSelectionMutator) and m.action == "enable"
        }
        sequenced = {
            m.tool_name for m in mutators if isinstance(m, ToolSequenceMutator)
        }
        for t in persona.mcp_server.tools:
            assert t in enabled and t in sequenced
        # no other persona's MCP tools are in this persona's mutation space
        for other in ALL_PERSONAS:
            if other.client_id == persona.client_id:
                continue
            assert not (enabled & other.all_tool_names())


# ===========================================================================
# Deliverable 2 — the AUTORUN adapts (PersonalizationRun, full loop).
# ===========================================================================


def _run_autoloop(persona: Persona, project_root: Path) -> tuple:
    """Drive a persona's FULL PersonalizationRun with persona-shaped mocks."""
    cp = _drive_persona(persona, project_root)

    # baseline = the persona-free base prompt, so promotion DEPENDS on the loop
    # adapting it toward this persona (not on the base already being persona-shaped).
    baseline_defn = {
        "header": {"agent_id": "writer"},
        "system_prompt": BASE_PROMPT,
    }

    installed: dict[str, str] = {}
    runner = FakeSessionRunner(installed)
    judge = PersonaJudge(persona)
    teacher = PersonaTeacher(persona)

    def agent_name_for(version: ComponentVersion) -> str:
        name = f"cand_{version.content_hash[:8]}"
        installed[name] = version.definition.get("system_prompt", "")
        return name

    run = PersonalizationRun(
        client_id=persona.client_id,
        client_spec=cp.spec,
        capability_bundle=cp.bundle,
        target=0.7,
        max_rounds=2,
    )
    result = run.run(
        baseline_definition=baseline_defn,
        runner=runner, judge=judge, teacher=teacher,
        agent_name_for=agent_name_for,
        project_root=project_root,
        snapshots_dir=project_root / ".oac" / "snapshots",
    )
    return cp, result, runner, judge, teacher


@pytest.mark.parametrize("persona", ALL_PERSONAS, ids=PERSONA_IDS)
def test_autorun_promotes_persona_shaped_winner(persona: Persona, tmp_path: Path):
    """The promoted winner reflects THIS persona (tone keyword + own bucket)."""
    cp, result, runner, judge, teacher = _run_autoloop(
        persona, tmp_path / persona.client_id
    )

    # the loop actually ran: runner/judge/teacher were all exercised
    assert runner.calls and judge.calls and teacher.calls
    assert result.probe_keys == [
        f"example_task:{i}" for i in range(len(persona.example_tasks))
    ]

    # a winner cleared the persona's bar and promoted into the persona's bucket
    assert result.promoted is True
    assert result.winner_score >= 0.7
    promoted_dir = tmp_path / persona.client_id / ".oac" / "promoted" / persona.client_id
    assert promoted_dir.exists()
    files = list(promoted_dir.glob("*.json"))
    assert files, f"nothing promoted into .oac/promoted/{persona.client_id}/"

    # the promoted definition carries THIS persona's tone keyword (it adapted)
    snap = json.loads(files[0].read_text())
    winning_prompt = snap["version"]["definition"]["system_prompt"]
    assert persona.tone_keyword in winning_prompt
    # and does NOT carry any OTHER persona's tone keyword (no cross-bleed)
    for other in ALL_PERSONAS:
        if other.client_id == persona.client_id:
            continue
        assert other.tone_keyword not in winning_prompt


def test_same_baseline_adapts_differently_per_persona(tmp_path: Path):
    """THE moat: the SAME base agent yields a DIFFERENT adapted agent per persona.

    Every persona starts from the identical BASE_PROMPT baseline; the only thing
    that differs is the persona's spec/tools/judge/teacher. We assert the three
    promoted winners are mutually distinct and each persona-shaped.
    """
    winners: dict[str, str] = {}
    promo_dirs: dict[str, Path] = {}
    for persona in ALL_PERSONAS:
        root = tmp_path / persona.client_id
        _, result, _, _, _ = _run_autoloop(persona, root)
        assert result.promoted is True
        promoted_dir = root / ".oac" / "promoted" / persona.client_id
        promo_dirs[persona.client_id] = promoted_dir
        snap = json.loads(next(promoted_dir.glob("*.json")).read_text())
        winners[persona.client_id] = snap["version"]["definition"]["system_prompt"]

    # all three started from the SAME baseline...
    # ...yet produced three DISTINCT adapted agents
    assert len(set(winners.values())) == 3, "same baseline did not adapt differently"

    # each winner is shaped by its OWN persona only
    for persona in ALL_PERSONAS:
        w = winners[persona.client_id]
        assert persona.tone_keyword in w
        for other in ALL_PERSONAS:
            if other.client_id != persona.client_id:
                assert other.tone_keyword not in w


# ===========================================================================
# Deliverable 1 — per-client ISOLATION of promotions.
# ===========================================================================


def test_promotions_are_isolated_per_client(tmp_path: Path):
    """Each persona's promotions land under its OWN .oac/promoted/<client_id>/."""
    # Run all three personas under ONE shared parent project root, so a collision
    # WOULD show up if the client buckets were not isolated.
    shared = tmp_path / "shared_platform"
    for persona in ALL_PERSONAS:
        _run_autoloop(persona, shared)

    promoted_root = shared / ".oac" / "promoted"
    buckets = {p.name for p in promoted_root.iterdir() if p.is_dir()}
    assert buckets == set(PERSONA_IDS), f"unexpected promotion buckets: {buckets}"

    # each bucket holds exactly its OWN persona's winner (carrying its keyword,
    # and none of the other personas' keywords).
    for persona in ALL_PERSONAS:
        bucket = promoted_root / persona.client_id
        files = list(bucket.glob("*.json"))
        assert files, f"{persona.client_id} bucket is empty"
        for f in files:
            snap = json.loads(f.read_text())
            prompt = snap["version"]["definition"]["system_prompt"]
            assert persona.tone_keyword in prompt
            for other in ALL_PERSONAS:
                if other.client_id != persona.client_id:
                    assert other.tone_keyword not in prompt
