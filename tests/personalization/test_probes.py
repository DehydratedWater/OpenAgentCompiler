"""Spec-seeded probes — example tasks become the loop's probes via ProbeCache."""

from __future__ import annotations

import json

import pytest

from open_agent_compiler.improvement.probe_cache import ProbeCache, ProbeResult
from open_agent_compiler.personalization import (
    ClientSpec,
    ExampleTask,
    example_task_probe_key,
    make_spec_probe_synthesizer,
    seed_probes_from_spec,
    spec_probe_keys,
)
from open_agent_compiler.personalization.probes import render_probe_text


def test_spec_probe_keys_one_per_task(valid_spec: ClientSpec) -> None:
    keys = spec_probe_keys(valid_spec)
    assert keys == ["example_task:0", "example_task:1"]
    assert example_task_probe_key(0) == "example_task:0"


def test_render_probe_appends_expected_outcome_hint() -> None:
    task = ExampleTask(prompt="Draft a reply", expected_outcome="Be apologetic")
    text = render_probe_text(task)
    assert "Draft a reply" in text
    assert "(A good result: Be apologetic)" in text


def test_render_probe_no_hint_when_no_outcome() -> None:
    text = render_probe_text(ExampleTask(prompt="Just do it"))
    assert text == "Just do it"
    assert "A good result" not in text


def test_synthesizer_returns_real_probe_for_each_task(valid_spec: ClientSpec) -> None:
    synth = make_spec_probe_synthesizer(valid_spec)
    result = synth("example_task:0")
    assert isinstance(result, ProbeResult)
    assert result.is_fallback is False
    assert "order #1234" in result.text


def test_synthesizer_raises_on_unknown_key(valid_spec: ClientSpec) -> None:
    synth = make_spec_probe_synthesizer(valid_spec)
    with pytest.raises(KeyError, match="unknown spec probe key"):
        synth("example_task:99")


def test_seed_probes_persists_real_probes(tmp_path, valid_spec: ClientSpec) -> None:
    cache_path = tmp_path / "probes.json"
    cache = seed_probes_from_spec(valid_spec, cache_path)
    assert isinstance(cache, ProbeCache)
    # all example-task probes are retrievable
    assert "order #1234" in cache.get("example_task:0")
    assert "reset their password" in cache.get("example_task:1")
    # and persisted to disk (the client's real tasks, never a fallback)
    on_disk = json.loads(cache_path.read_text())
    assert set(on_disk) == {"example_task:0", "example_task:1"}
    assert "order #1234" in on_disk["example_task:0"]


def test_seed_probes_requires_usable_spec(tmp_path) -> None:
    partial = ClientSpec(goal="g", example_tasks=(ExampleTask(prompt="t"),))
    # usable() also needs success_criteria
    with pytest.raises(ValueError):
        seed_probes_from_spec(partial, tmp_path / "p.json")


def test_seed_probes_reloads_from_disk(tmp_path, valid_spec: ClientSpec) -> None:
    cache_path = tmp_path / "probes.json"
    seed_probes_from_spec(valid_spec, cache_path)
    # a fresh cache over the same path + synth loads the persisted probes
    cache2 = ProbeCache(cache_path, synthesize=make_spec_probe_synthesizer(valid_spec))
    cache2.load()
    assert "order #1234" in cache2.as_dict()["example_task:0"]
