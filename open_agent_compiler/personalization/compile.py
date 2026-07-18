"""Per-client personalized compile — base fleet + client overlay + merged surface.

Phase E's first seam. A base SaaS fleet is compiled, per client, with THREE
client-specific overlays applied on top of the unchanged base behavior:

  1. **Client prompt overlay** (`ClientOverlay`, a `VariantSpec` mirroring how
     `SplitProfile` overlays per model_class): spec-derived prompt additions —
     the client's goal / preferences / constraints — are appended to each
     agent's `system_prompt` so every agent in the client's fleet knows the
     client's workflow. Base (no client) behavior is unchanged because the
     overlay is only applied on the personalized compile path.

  2. **Merged capability surface** (`MergedCapabilitySurface`): the compiler
     emits only per-agent `permission.mcp` today, not a top-level `mcp` section.
     `write_personalized_opencode_json` writes an `opencode.json` at the project
     root carrying the client's MCP servers (`opencode_json_fragment()`) plus the
     merged per-agent tool allow-list — so the client's tools are actually wired
     into the opencode project the loop runs from.

  3. **Datasource context** (`DatasourceProfile.context_block()`): each connected
     datasource's auto-profiled layout is injected into the agent's prompt (via a
     `PromptAssembler` of stable ContextBlocks) so the agent knows the client's
     data structure up front.

`compile_personalized(...)` ties them together and returns a
`PersonalizedCompile` describing the per-client opencode project root (with the
compiled fleet under `.opencode/agents/`, an `opencode.json` at the root, and
flat-named candidates installable via the Phase-0 helpers — `flat_name_for`).

Pure file IO + pure data; no opencode/qwen/z.ai/network calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.compiler.script import CompileScript, Factory
from open_agent_compiler.datasource.profile import DatasourceProfile
from open_agent_compiler.improvement.compile_helpers import flat_candidate_name
from open_agent_compiler.model.core.agent_model import AgentVariant
from open_agent_compiler.model.core.capability_bundle import (
    ClientCapabilityBundle,
    MergedCapabilitySurface,
    merge_capabilities,
)
from open_agent_compiler.model.core.context_blocks import ContextBlock, PromptAssembler
from open_agent_compiler.model.core.variant_spec import VariantSpec
from open_agent_compiler.personalization.spec import ClientSpec


# ---- client prompt overlay -------------------------------------------------


def build_client_prompt_block(spec: ClientSpec) -> str:
    """Render the client's goal/preferences/constraints as a prompt block.

    This is the spec-derived prompt addition the overlay appends to each
    agent. It is deterministic (no LLM) so the base structure is stable; the
    autoloop's teacher refines the wording from real trajectories later.
    """
    lines: list[str] = ["## CLIENT CONTEXT", f"Your job for this client: {spec.goal.strip()}"]
    if spec.preferences:
        lines.append("Preferences (honour these):")
        lines.extend(f"  - {p}" for p in spec.preferences)
    if spec.constraints:
        lines.append("Hard constraints (never violate):")
        lines.extend(f"  - {c}" for c in spec.constraints)
    return "\n".join(lines)


class ClientOverlay(VariantSpec):
    """A `VariantSpec` that overlays a client's spec + datasource context.

    Mirrors `SplitProfile` (a per-class overlay): both subclass `VariantSpec`
    and customise how a base agent is transformed for one compile pass. Where
    `SplitProfile` swaps the preset per `model_class`, `ClientOverlay` keeps each
    agent's OWN model and instead appends client-specific prompt content
    (`client_prompt_block` + each datasource profile's `context_block()`),
    applied through `overlay_variant` below. The base fleet is untouched.

    `datasource_profiles` are injected as stable `ContextBlock`s so the agent
    knows the client's data layout; they sit early in the assembled prompt
    (prefill-cache-friendly) per the PromptAssembler contract.
    """

    model_config = ConfigDict(frozen=True)

    client_id: str = Field(description="Tenant this overlay personalizes for.")
    client_prompt_block: str = ""
    datasource_summaries: tuple[str, ...] = Field(
        default=(),
        description="Pre-rendered datasource context summaries to inject.",
    )

    def applies_to(self, variant: AgentVariant) -> bool:
        """Opt every agent OUT of `apply_variant`'s preset/postfix swap.

        The overlay does NOT reroute the model (each agent keeps its own) — the
        prompt overlay is applied separately by `overlay_variant` through the
        `_OverlayFactory`. Returning False makes the compiler's `apply_variant`
        a no-op, so only the prompt overlay (already baked into the registry)
        survives. The per-client project root gives isolation, so no postfix is
        needed.
        """
        return False

    @classmethod
    def from_spec(
        cls,
        *,
        client_id: str,
        spec: ClientSpec,
        preset: Any,
        datasource_profiles: tuple[DatasourceProfile, ...] = (),
        postfix: str = "",
    ) -> "ClientOverlay":
        """Build a ClientOverlay from a ClientSpec + datasource profiles."""
        return cls(
            name=f"client:{client_id}",
            postfix=postfix,
            preset=preset,
            client_id=client_id,
            client_prompt_block=build_client_prompt_block(spec),
            datasource_summaries=tuple(
                p.summary for p in datasource_profiles if p.summary
            ),
        )

    def assemble_prompt(self, base_system_prompt: str) -> str:
        """Compose base prompt + datasource blocks + client block, cache-ordered.

        Uses a PromptAssembler so the datasource layout (stable) sits ahead of
        the client overlay (also stable) and the base prompt keeps its place —
        the same volatility-aware ordering the rest of the framework uses.
        """
        blocks: list[ContextBlock] = []
        if base_system_prompt:
            blocks.append(ContextBlock(
                name="base", volatility="immutable", content=base_system_prompt,
            ))
        for i, summary in enumerate(self.datasource_summaries):
            blocks.append(ContextBlock(
                name=f"datasource:{i}", volatility="stable", content=summary,
            ))
        if self.client_prompt_block:
            blocks.append(ContextBlock(
                name="client", volatility="stable", content=self.client_prompt_block,
            ))
        if not blocks:
            return base_system_prompt
        return PromptAssembler(blocks=blocks).compose()


def overlay_variant(overlay: ClientOverlay, variant: AgentVariant) -> AgentVariant:
    """Return a copy of `variant` with the client overlay applied.

    Keeps the agent's own `model_parameters` (the overlay does NOT reroute the
    model — that's `SplitProfile`'s job). The agent's `system_prompt` is replaced
    with the assembled prompt (base + datasource context + client block). The
    original variant is left untouched (Pydantic model_copy), so the base fleet
    stays reusable. Postfix is governed by the compile config (the per-client
    project root provides isolation, so it is empty by default).
    """
    defn = variant.agent_definition
    new_prompt = overlay.assemble_prompt(defn.system_prompt)
    new_defn = defn.model_copy(update={"system_prompt": new_prompt})
    return variant.model_copy(update={"agent_definition": new_defn})


# ---- opencode.json emit (top-level mcp + merged allow-list) -----------------


def build_personalized_opencode_json(
    surface: MergedCapabilitySurface,
    *,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the opencode.json dict for a per-client project.

    Merges `surface.opencode_json_fragment()` (the `{"mcp": {...}}` section the
    compiler does NOT emit today) onto an optional `base` config, and records the
    merged per-agent tool `allow_list` under a top-level `tools` key so the
    client's enabled tools are discoverable. Pure dict assembly.

    opencode's config schema requires `tools` to be a `{name: bool}` enable-map
    (a JSON object), NOT a list — emitting a list makes opencode reject the whole
    config ("Expected object | undefined, got [...] tools"), which silently breaks
    every live agent run (empty output → every autoloop outcome scores 0).
    """
    out: dict[str, Any] = dict(base or {})
    out.update(surface.opencode_json_fragment())  # {"mcp": {...}}
    if surface.allow_list:
        out["tools"] = {name: True for name in surface.allow_list}
    return out


def write_personalized_opencode_json(
    project_root: Path,
    surface: MergedCapabilitySurface,
    *,
    base: dict[str, Any] | None = None,
) -> Path:
    """Write the per-client `opencode.json` at the project root. Returns its path.

    This is the seam that wires the client's MCP servers + merged allow-list into
    the actual opencode project the loop runs from (the compiler only emits the
    per-agent `permission.mcp` frontmatter). Re-reads an existing opencode.json as
    the `base` when none is supplied, so a re-compile preserves unrelated config.
    """
    project_root = Path(project_root)
    project_root.mkdir(parents=True, exist_ok=True)
    path = project_root / "opencode.json"
    if base is None and path.exists():
        try:
            base = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            base = None
    config = build_personalized_opencode_json(surface, base=base)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


# ---- the personalized compile ----------------------------------------------


class PersonalizedCompile(BaseModel):
    """Result of `compile_personalized` — the per-client opencode project root."""

    model_config = ConfigDict(frozen=True)

    client_id: str
    project_root: Path
    opencode_json: Path
    agents_dir: Path
    allow_list: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    written_files: tuple[Path, ...] = ()

    def flat_name_for(self, *, prefix: str = "cand") -> str:
        """A flat candidate name for installing a tuned agent into this root.

        Thin pass-through to the Phase-0 `flat_candidate_name` so callers stay
        within this module's surface; install with
        `flat_candidate_from_project_root(project_root=self.project_root, ...)`.
        """
        return flat_candidate_name(prefix)


def compile_personalized(
    client_id: str,
    spec: ClientSpec,
    bundle: ClientCapabilityBundle,
    target: Path,
    *,
    factory: Factory,
    config: str,
    preset: Any,
    datasource_profiles: tuple[DatasourceProfile, ...] = (),
    collision_policy: str = "namespace_client",
    postfix: str = "",
    opencode_base: dict[str, Any] | None = None,
) -> PersonalizedCompile:
    """Compile a base fleet personalized for one client into a project root.

    Pipeline:
      1. Merge the client's capability bundle → `MergedCapabilitySurface`
         (built-in ∪ client MCP ∪ datasource tools, collision policy applied).
      2. Compile the base fleet under a `ClientOverlay` VariantSpec (spec prompt
         additions + datasource context applied to every agent) via the existing
         `CompileScript`, with `client_id` flowed into the CompilationContext so
         per-client promotions (`.oac/promoted/<client_id>/`) are consulted.
      3. Write `opencode.json` at the root with the client's `mcp` section +
         merged allow-list.

    Returns a `PersonalizedCompile`. Base (no client) compiles are unaffected —
    this is an additive, separate entry point.
    """
    target = Path(target)
    surface = merge_capabilities(bundle, policy=collision_policy)  # type: ignore[arg-type]

    overlay = ClientOverlay.from_spec(
        client_id=client_id,
        spec=spec,
        preset=preset,
        datasource_profiles=datasource_profiles,
        postfix=postfix,
    )

    # Compile the base fleet under the overlay. We post-process the resolved
    # tree with `overlay_variant` (keeps each agent's own model, applies the
    # client prompt) by wrapping the factory's variants through a thin variant
    # spec pass. CompileScript drives compilation + the per-client context.
    script = _client_compile_script(
        target=target,
        factory=factory,
        config=config,
        overlay=overlay,
        client_id=client_id,
    )
    result = script.run()

    opencode_json = write_personalized_opencode_json(
        target, surface, base=opencode_base,
    )

    return PersonalizedCompile(
        client_id=client_id,
        project_root=target,
        opencode_json=opencode_json,
        agents_dir=target / ".opencode" / "agents",
        allow_list=surface.allow_list,
        mcp_servers=tuple(surface.mcp_config.keys()),
        written_files=tuple(result.written_files),
    )


def _client_compile_script(
    *,
    target: Path,
    factory: Factory,
    config: str,
    overlay: ClientOverlay,
    client_id: str,
) -> CompileScript:
    """Build a CompileScript that compiles the fleet under the client overlay.

    The overlay is registered as the single VariantSpec so the compiler runs one
    pass with the client's postfix; the prompt overlay itself is applied by
    `overlay_variant` inside a factory wrapper, keeping each agent's own model.
    """
    wrapped = _OverlayFactory(factory=factory, overlay=overlay)
    return CompileScript(
        target=target,
        config=config,
        factory=wrapped,
        clean=False,
        variants=[overlay],
        client_id=client_id,
    )


class _OverlayFactory:
    """Callable factory wrapper that applies the client overlay to each agent.

    CompileScript calls the factory under the active CompilationContext; this
    wrapper re-resolves the base registry and overlays every registered variant's
    prompt with `overlay_variant`, returning a registry whose agents carry the
    client context. Keeps the base factory untouched.
    """

    def __init__(self, *, factory: Factory, overlay: ClientOverlay) -> None:
        self._factory = factory
        self._overlay = overlay

    def __call__(self):  # -> AgentRegistry
        registry = self._factory()
        for agent_id, variant in list(registry._agents.items()):  # noqa: SLF001
            registry._agents[agent_id] = overlay_variant(self._overlay, variant)
        return registry


__all__ = [
    "build_client_prompt_block",
    "ClientOverlay",
    "overlay_variant",
    "build_personalized_opencode_json",
    "write_personalized_opencode_json",
    "PersonalizedCompile",
    "compile_personalized",
]
