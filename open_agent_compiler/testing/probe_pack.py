"""ProbePack — persisted, regenerable probe sets that load as AgentTests.

A probe pack is a JSON file of judge-graded probes for one component,
typically synthesized offline from REAL usage data (a chat corpus, support
tickets, logs) by a teacher model. Packs decouple expensive probe synthesis
from the improvement loop: generate once, version the JSON, load on every
run. A missing pack degrades to [] so consumers can always fall back to
their default test set.

Consumers own *generation* (what corpus, which teacher, what slicing);
the framework owns the *shape* and the pack → AgentTest conversion.

Reference generator shape: sample a real chat corpus per agent domain and
have a teacher model (e.g. GLM) write the probes.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from open_agent_compiler.model.core.test_model import AgentTest, LLMJudgeEvaluator


class PackProbe(BaseModel):
    """One grounded probe: a self-contained user message + judge rubric."""

    name: str
    prompt: str
    criteria: str
    pass_threshold: float = 0.7
    # Short note on which real source messages inspired this probe (provenance).
    source_hint: str = ""


class ProbePack(BaseModel):
    """A persisted set of probes for one component, regenerable from source data."""

    agent_id: str
    generated_at: str
    source: str = ""
    teacher: str = ""
    probes: list[PackProbe] = Field(min_length=1)


def load_pack(path: Path | str) -> ProbePack | None:
    """Load a pack JSON; None when the file is missing or unparseable
    (a broken pack must degrade to the consumer's default tests, not crash
    the improvement run)."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return ProbePack.model_validate(json.loads(p.read_text()))
    except Exception:
        return None


def pack_to_tests(
    pack: ProbePack, *, prompt_suffix: str = "", name_prefix: str | None = None,
) -> list[AgentTest]:
    """Convert a pack into graded judge AgentTests.

    `prompt_suffix` is appended to every probe prompt — consumers use it for
    anti-meta guards ("reply with your actual response, do not describe your
    role"). `name_prefix` defaults to "<agent_id>::pack:".
    """
    prefix = name_prefix if name_prefix is not None else f"{pack.agent_id}::pack:"
    return [
        AgentTest(
            name=f"{prefix}{probe.name}",
            prompt=probe.prompt.rstrip() + prompt_suffix,
            evaluators=(
                LLMJudgeEvaluator(
                    name=probe.name,
                    criteria=probe.criteria,
                    pass_threshold=probe.pass_threshold,
                ),
            ),
        )
        for probe in pack.probes
    ]
