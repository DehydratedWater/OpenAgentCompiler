"""Structured per-section prompts + the section-aware mutator."""

from __future__ import annotations

from open_agent_compiler.improvement.mutators import (
    MutationContext,
    SectionRewriterMutator,
    make_section_mutators,
)
from open_agent_compiler.improvement.mutators.llm import _StubLLM
from open_agent_compiler.improvement.prompt_sections import (
    PromptSection,
    apply_sections_to_definition,
    get_sections,
    render_sections,
    set_sections,
    split_into_sections,
)
from open_agent_compiler.improvement.version import ComponentVersion

RICH = """\
You are Nova.

## Planning Protocol
PARSE, INTENT, EMIT. Always end with emit_guidance.

## Media Capability
You CAN send selfies via persona/nova_selfie. Never claim to be text-only.

## Delivery Contract
Every turn ends with exactly ONE emit_guidance call."""


# ── model + render ──


def test_render_orders_and_skips_empty():
    secs = [
        PromptSection(name="b", content="B", order=1),
        PromptSection(name="a", content="A", order=0),
        PromptSection(name="empty", content="   ", order=2),
    ]
    assert render_sections(secs) == "A\n\nB"


def test_render_accepts_dicts():
    assert render_sections([{"name": "x", "content": "hello"}]) == "hello"


# ── split ──


def test_split_into_sections_headers_and_intro():
    secs = split_into_sections(RICH)
    names = [s.name for s in secs]
    assert names[0] == "intro"
    assert "planning_protocol" in names
    assert "media_capability" in names
    assert "delivery_contract" in names
    # each non-intro section keeps its header line
    media = next(s for s in secs if s.name == "media_capability")
    assert media.content.startswith("## Media Capability")


def test_split_round_trips():
    secs = split_into_sections(RICH)
    # render is stable up to inter-block whitespace
    assert "PARSE, INTENT, EMIT" in render_sections(secs)
    assert "persona/nova_selfie" in render_sections(secs)


def test_split_marks_immutable():
    secs = split_into_sections(RICH, immutable_names={"delivery_contract"})
    dc = next(s for s in secs if s.name == "delivery_contract")
    assert dc.mutable is False
    media = next(s for s in secs if s.name == "media_capability")
    assert media.mutable is True


def test_split_no_headers_single_body():
    secs = split_into_sections("just a flat prompt with no headers")
    assert len(secs) == 1 and secs[0].name == "body"


# ── definition helpers ──


def test_set_and_apply_derive_system_prompt():
    defn = {"name": "persona/x", "system_prompt": "stale"}
    secs = split_into_sections(RICH)
    defn = set_sections(defn, secs)
    assert defn["system_prompt"] == render_sections(secs)
    # apply re-derives idempotently
    defn["system_prompt"] = "tampered"
    assert apply_sections_to_definition(defn)["system_prompt"] == render_sections(secs)


def test_apply_noop_without_sections():
    defn = {"name": "y", "system_prompt": "flat"}
    assert apply_sections_to_definition(defn)["system_prompt"] == "flat"


# ── the section-aware mutator: improve ONE, keep the rest ──


def _agent_version(defn: dict) -> ComponentVersion:
    return ComponentVersion.of(component_id="persona/x", kind="agent", definition=defn)


def test_section_rewriter_changes_only_its_section():
    defn = set_sections({"name": "persona/x"}, split_into_sections(RICH))
    v = _agent_version(defn)
    llm = _StubLLM(response="## Planning Protocol\nPARSE, INTENT, VERIFY, EMIT — improved.")
    mut = SectionRewriterMutator("planning_protocol")
    out = mut.mutate(v, MutationContext(llm=llm))
    assert out is not None
    new = get_sections(out.definition)
    by_name = {s.name: s for s in new}
    # only the targeted section changed
    assert "improved" in by_name["planning_protocol"].content
    assert by_name["media_capability"].content == next(
        s for s in get_sections(defn) if s.name == "media_capability"
    ).content
    # system_prompt re-derived and consistent
    assert out.definition["system_prompt"] == render_sections(new)
    assert "nova_selfie" in out.definition["system_prompt"]  # other sections survive


def test_section_rewriter_skips_immutable_section():
    secs = split_into_sections(RICH, immutable_names={"delivery_contract"})
    v = _agent_version(set_sections({"name": "persona/x"}, secs))
    mut = SectionRewriterMutator("delivery_contract")
    assert mut.mutate(v, MutationContext(llm=_StubLLM("anything"))) is None


def test_section_rewriter_never_empties_required_section():
    v = _agent_version(set_sections({"name": "persona/x"}, split_into_sections(RICH)))
    mut = SectionRewriterMutator("planning_protocol")
    # LLM returns empty → structural guarantee: skip, do not drop the section
    assert mut.mutate(v, MutationContext(llm=_StubLLM("   "))) is None


def test_section_rewriter_skips_without_llm_or_sections():
    v_sec = _agent_version(set_sections({"name": "persona/x"}, split_into_sections(RICH)))
    assert SectionRewriterMutator("planning_protocol").mutate(v_sec, MutationContext()) is None
    v_flat = _agent_version({"name": "persona/x", "system_prompt": "flat"})
    assert SectionRewriterMutator("planning_protocol").mutate(
        v_flat, MutationContext(llm=_StubLLM("x"))
    ) is None


def test_make_section_mutators_one_per_mutable_section():
    secs = split_into_sections(RICH, immutable_names={"delivery_contract"})
    defn = set_sections({"name": "persona/x"}, secs)
    muts = make_section_mutators(defn)
    targeted = {m.section_name for m in muts}
    assert "planning_protocol" in targeted
    assert "media_capability" in targeted
    assert "delivery_contract" not in targeted  # immutable → no mutator
    # non-sectioned definition → no section mutators (caller falls back)
    assert make_section_mutators({"name": "z", "system_prompt": "flat"}) == []
