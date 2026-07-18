"""ProbeCache — disk-cached, parallel probe synthesis; fallbacks never persisted."""

from __future__ import annotations

import json
from pathlib import Path

from open_agent_compiler.improvement.probe_cache import ProbeCache, ProbeResult


def test_get_synthesizes_and_caches(tmp_path: Path) -> None:
    calls = []

    def synth(key: str) -> ProbeResult:
        calls.append(key)
        return ProbeResult(text=f"probe for {key}")

    cache = ProbeCache(tmp_path / "probes.json", synthesize=synth)
    assert cache.get("a") == "probe for a"
    assert cache.get("a") == "probe for a"  # second hit is cached
    assert calls == ["a"]  # synthesised once


def test_save_persists_only_real_probes(tmp_path: Path) -> None:
    def synth(key: str) -> ProbeResult:
        # 'bad' is a fallback (teacher unavailable); 'good' is real.
        return ProbeResult(text=f"{key}-text", is_fallback=(key == "bad"))

    p = tmp_path / "probes.json"
    cache = ProbeCache(p, synthesize=synth)
    cache.get("good")
    cache.get("bad")
    cache.save()

    data = json.loads(p.read_text())
    assert data == {"good": "good-text"}  # fallback NOT persisted


def test_fallback_is_retried_not_served_from_cache(tmp_path: Path) -> None:
    state = {"fallback": True}
    calls = []

    def synth(key: str) -> ProbeResult:
        calls.append(key)
        return ProbeResult(text="x", is_fallback=state["fallback"])

    cache = ProbeCache(tmp_path / "p.json", synthesize=synth)
    cache.get("a")            # fallback
    state["fallback"] = False
    cache.get("a")            # re-synthesised (not served from fallback cache)
    assert calls == ["a", "a"]
    # now it's real -> served from cache, no third call
    cache.get("a")
    assert calls == ["a", "a"]


def test_load_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "probes.json"
    p.write_text(json.dumps({"x": "saved probe"}))

    def synth(key: str) -> ProbeResult:
        raise AssertionError("should not synthesise a loaded key")

    cache = ProbeCache(p, synthesize=synth)
    assert cache.get("x") == "saved probe"


def test_load_tolerates_corrupt_cache(tmp_path: Path) -> None:
    p = tmp_path / "p.json"
    p.write_text("{ not json")
    cache = ProbeCache(p, synthesize=lambda k: ProbeResult(text="fresh"))
    assert cache.get("a") == "fresh"  # corrupt file ignored, doesn't crash


def test_prewarm_synthesizes_missing_in_parallel_and_persists(tmp_path: Path) -> None:
    def synth(key: str) -> ProbeResult:
        return ProbeResult(text=f"{key}!")

    p = tmp_path / "p.json"
    cache = ProbeCache(p, synthesize=synth)
    n = cache.prewarm(["a", "b", "c"], workers=4)
    assert n == 3
    assert json.loads(p.read_text()) == {"a": "a!", "b": "b!", "c": "c!"}
    # already-warm keys aren't re-done
    assert cache.prewarm(["a", "b", "c"]) == 0


def test_prewarm_redoes_fallback_only_keys(tmp_path: Path) -> None:
    def synth(key: str) -> ProbeResult:
        return ProbeResult(text="t", is_fallback=(key == "f"))

    cache = ProbeCache(tmp_path / "p.json", synthesize=synth)
    cache.prewarm(["r", "f"])
    # 'f' was a fallback -> still considered missing on the next prewarm
    assert cache.prewarm(["r", "f"]) == 1
