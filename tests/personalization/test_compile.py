"""Phase E client-overlay compile: prompt overlay + opencode.json + datasource."""

from __future__ import annotations

import json


from open_agent_compiler.datasource.profile import DatasourceProfile
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
    ClientMCPServer,
    merge_capabilities,
)
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.personalization.compile import (
    ClientOverlay,
    build_client_prompt_block,
    build_personalized_opencode_json,
    compile_personalized,
    overlay_variant,
    write_personalized_opencode_json,
)
from open_agent_compiler.personalization.spec import ClientSpec, ExampleTask


# ---- fixtures ----------------------------------------------------------


def _factory():
    reg = AgentRegistry()
    a = AgentDefinition(
        header=AgentHeader(agent_id="x", name="support-bot", description="d"),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="You are a support agent.",
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
        name="overlay", provider="vllm", model_id="ignored",
        sampling=SamplingDefaults(temperature=0.0),
    )


def _spec():
    return ClientSpec(
        goal="Triage support email and draft replies",
        preferences=("Friendly tone",),
        constraints=("Never promise a refund",),
        example_tasks=(ExampleTask(prompt="Reply to an angry customer."),),
        success_criteria=("Reply is on-topic and friendly",),
    )


def _bundle():
    return ClientCapabilityBundle(
        client_id="acme",
        builtin_tools=("search", "draft"),
        mcp_servers=(
            ClientMCPServer(
                name="acme_drive", transport="remote",
                url="https://mcp.acme/drive", tools=("drive_search", "draft"),
            ),
        ),
    )


# ---- prompt overlay ----------------------------------------------------


def test_client_prompt_block_carries_goal_prefs_constraints():
    block = build_client_prompt_block(_spec())
    assert "Triage support email" in block
    assert "Friendly tone" in block
    assert "Never promise a refund" in block


def test_overlay_keeps_model_and_appends_client_context():
    overlay = ClientOverlay.from_spec(
        client_id="acme", spec=_spec(), preset=_preset()
    )
    reg = _factory()
    variant = reg.resolve_config("prod")["primary"]
    out = overlay_variant(overlay, variant)
    # model untouched
    assert out.model_parameters.model_name == "local/qwen"
    # base prompt preserved + client block appended
    assert "You are a support agent." in out.agent_definition.system_prompt
    assert "Triage support email" in out.agent_definition.system_prompt
    assert "Never promise a refund" in out.agent_definition.system_prompt


def test_overlay_injects_datasource_summary():
    profile = DatasourceProfile(
        datasource_name="acme_drive", kind="gdrive",
        summary="Client drive: folders Invoices/, Contracts/.",
    )
    overlay = ClientOverlay.from_spec(
        client_id="acme", spec=_spec(), preset=_preset(),
        datasource_profiles=(profile,),
    )
    reg = _factory()
    variant = reg.resolve_config("prod")["primary"]
    out = overlay_variant(overlay, variant)
    assert "Client drive: folders Invoices/" in out.agent_definition.system_prompt


def test_overlay_applies_to_is_false_so_model_not_rerouted():
    # ClientOverlay must opt every agent out of apply_variant's preset swap.
    overlay = ClientOverlay.from_spec(
        client_id="acme", spec=_spec(), preset=_preset()
    )
    reg = _factory()
    variant = reg.resolve_config("prod")["primary"]
    assert overlay.applies_to(variant) is False


# ---- opencode.json emit ------------------------------------------------


def test_build_opencode_json_has_mcp_and_allow_list():
    surface = merge_capabilities(_bundle())
    cfg = build_personalized_opencode_json(surface)
    assert "acme_drive" in cfg["mcp"]
    assert cfg["mcp"]["acme_drive"]["type"] == "remote"
    # 'draft' collides with builtin -> namespaced 'client_draft' by default policy
    assert "client_draft" in cfg["tools"]
    assert "drive_search" in cfg["tools"]
    assert "search" in cfg["tools"]  # builtin preserved


def test_write_opencode_json_round_trips(tmp_path):
    surface = merge_capabilities(_bundle())
    path = write_personalized_opencode_json(tmp_path, surface)
    assert path == tmp_path / "opencode.json"
    data = json.loads(path.read_text())
    assert "acme_drive" in data["mcp"]


def test_write_opencode_json_preserves_existing_base(tmp_path):
    (tmp_path / "opencode.json").write_text(json.dumps({"theme": "dark"}))
    surface = merge_capabilities(_bundle())
    path = write_personalized_opencode_json(tmp_path, surface)
    data = json.loads(path.read_text())
    assert data["theme"] == "dark"  # unrelated config kept
    assert "acme_drive" in data["mcp"]


# ---- full compile_personalized -----------------------------------------


def test_compile_personalized_end_to_end(tmp_path):
    result = compile_personalized(
        "acme", _spec(), _bundle(), tmp_path,
        factory=_factory, config="prod", preset=_preset(),
    )
    # project layout
    assert result.project_root == tmp_path
    assert result.opencode_json.exists()
    assert result.agents_dir == tmp_path / ".opencode" / "agents"
    # opencode.json wired the client MCP + merged allow-list
    cfg = json.loads(result.opencode_json.read_text())
    assert "acme_drive" in cfg["mcp"]
    assert "drive_search" in cfg["tools"]
    assert result.mcp_servers == ("acme_drive",)
    assert "search" in result.allow_list
    # compiled agent carries the client overlay in its prompt
    agent_md = (result.agents_dir / "primary.md").read_text()
    assert "Triage support email" in agent_md
    assert "Never promise a refund" in agent_md
    assert "You are a support agent." in agent_md


def test_compile_personalized_with_datasource(tmp_path):
    profile = DatasourceProfile(
        datasource_name="acme_drive", kind="gdrive",
        summary="Drive layout: Invoices/ and Contracts/ folders.",
    )
    result = compile_personalized(
        "acme", _spec(), _bundle(), tmp_path,
        factory=_factory, config="prod", preset=_preset(),
        datasource_profiles=(profile,),
    )
    agent_md = (result.agents_dir / "primary.md").read_text()
    assert "Drive layout: Invoices/" in agent_md


def test_flat_name_for_returns_candidate_name(tmp_path):
    result = compile_personalized(
        "acme", _spec(), _bundle(), tmp_path,
        factory=_factory, config="prod", preset=_preset(),
    )
    name = result.flat_name_for()
    assert name.startswith("cand_")
