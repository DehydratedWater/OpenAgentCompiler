"""Spec-seeded probes — the autoloop's probes ARE the client's example tasks.

Phase 0's `ProbeCache`/`ProbeSynthesizer` synthesise a generic probe per agent
via a teacher call. For a per-client loop we want the OPPOSITE: the graded probes
should be the client's OWN concrete `ClientSpec.example_tasks`, so the loop climbs
the real work the client described — not a generic role exercise.

This module bridges the two: it builds a `ProbeSynthesizer` whose key is an
example-task id (`example_task:<n>`) and which returns that task's prompt as a
REAL (non-fallback) `ProbeResult`. Feeding that synthesiser to a `ProbeCache`
gives the loop the Phase-0 machinery (disk cache, parallel prewarm, the
'never persist fallbacks' invariant) while the probe content is the client's task.

The synthesiser raises on an unknown key (the loop should only ask for the keys
this spec advertises via `spec_probe_keys`), so a stray key can never be silently
turned into a fallback that pollutes the cache.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.improvement.probe_cache import ProbeCache, ProbeResult, ProbeSynthesizer
from open_agent_compiler.personalization.spec import ClientSpec, ExampleTask

# Probe-cache key prefix for a spec example task. Stable + filesystem-safe so the
# same task maps to the same cache slot across runs.
PROBE_KEY_PREFIX = "example_task:"


def example_task_probe_key(index: int) -> str:
    """The probe-cache key for the `index`-th example task (0-based)."""
    return f"{PROBE_KEY_PREFIX}{index}"


def spec_probe_keys(spec: ClientSpec) -> list[str]:
    """The probe keys this spec advertises — one per example task, in order."""
    return [example_task_probe_key(i) for i in range(len(spec.example_tasks))]


def render_probe_text(task: ExampleTask) -> str:
    """The probe text for one example task.

    The task prompt IS the probe. When the client noted an expected outcome we
    append it as a soft '(A good result: …)' hint so the graded session has the
    client's success signal in-band, mirroring how the outcome judge weaves an
    expected path in as a hint rather than a hard match.
    """
    text = task.prompt.strip()
    note = task.expected_outcome.strip()
    if note:
        text = f"{text}\n\n(A good result: {note})"
    return text


def make_spec_probe_synthesizer(spec: ClientSpec) -> ProbeSynthesizer:
    """Build a `ProbeSynthesizer` over a spec's example tasks.

    The returned callable maps `example_task:<n>` -> the n-th task rendered as a
    REAL (non-fallback) ProbeResult, so the cache persists it. An unknown key
    raises (it must not become a silently-persisted fallback).
    """
    by_key = {
        example_task_probe_key(i): render_probe_text(t)
        for i, t in enumerate(spec.example_tasks)
    }

    def synthesize(key: str) -> ProbeResult:
        if key not in by_key:
            raise KeyError(
                f"unknown spec probe key {key!r}; valid keys: {sorted(by_key)}"
            )
        return ProbeResult(text=by_key[key], is_fallback=False)

    return synthesize


def seed_probes_from_spec(
    spec: ClientSpec,
    cache_path: str | Path,
    *,
    prewarm: bool = True,
    workers: int = 4,
) -> ProbeCache:
    """Build a `ProbeCache` seeded from the client's example tasks and persist it.

    Requires a usable spec (≥1 example task). Returns the populated `ProbeCache`;
    when `prewarm=True` (default) every example-task probe is materialised + the
    real probes are written to `cache_path` (fallbacks are impossible here, so the
    Phase-0 'never persist fallbacks' contract is upheld trivially).
    """
    spec.require_usable()
    cache = ProbeCache(
        Path(cache_path), synthesize=make_spec_probe_synthesizer(spec)
    )
    if prewarm:
        cache.prewarm(spec_probe_keys(spec), workers=workers)
    return cache


__all__ = [
    "PROBE_KEY_PREFIX",
    "example_task_probe_key",
    "spec_probe_keys",
    "render_probe_text",
    "make_spec_probe_synthesizer",
    "seed_probes_from_spec",
]
