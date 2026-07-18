"""Disk-cached, parallel probe synthesis for the autoloop (Phase 0 hardening).

A "probe" is one concrete, self-contained task used to exercise an agent's role
(the graded signal the loop climbs). Synthesising a probe is a teacher (strong
model) call per agent; doing many sequentially at setup time stalled a whole run
for tens of minutes. This caches synthesised probes to disk and pre-warms them in
PARALLEL so setup is instant after the first time.

CRITICAL invariant (the v4 fix): persist ONLY real synthesised probes, never an
offline fallback — a transient teacher blip must not poison the cache permanently.
A synthesiser therefore returns a `ProbeResult(text, is_fallback)`; only
non-fallback results are written to disk.

Generic over the synthesiser, so it is decoupled from any model/SDK and fully
testable with a stub. Thread-safe for the parallel pre-warm.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from pydantic import BaseModel


class ProbeResult(BaseModel):
    """A synthesised probe + whether it is an offline fallback.

    `is_fallback=True` marks a degraded result produced when the teacher was
    unavailable; the cache uses this flag to refuse to persist it.
    """

    text: str
    is_fallback: bool = False


# A synthesiser maps a key (e.g. an agent id) -> ProbeResult.
ProbeSynthesizer = Callable[[str], ProbeResult]


class ProbeCache:
    """Thread-safe, disk-backed cache of synthesised probes.

    Usage:
        cache = ProbeCache(path, synthesize=my_synth)
        cache.load()                 # read existing real probes once
        cache.prewarm(keys, workers=12)   # parallel-synthesise the missing ones
        probe = cache.get("agent-id")     # cached or freshly synthesised
    """

    def __init__(
        self,
        path: Path,
        *,
        synthesize: ProbeSynthesizer,
    ) -> None:
        self.path = Path(path)
        self._synthesize = synthesize
        self._cache: dict[str, str] = {}
        self._fallbacks: set[str] = set()
        self._lock = threading.Lock()
        self._loaded = False

    # --- disk round-trip -----------------------------------------------------

    def load(self) -> None:
        """Load persisted probes from disk ONCE (idempotent, thread-safe)."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                if self.path.exists():
                    data = json.loads(self.path.read_text())
                    if isinstance(data, dict):
                        self._cache.update(
                            {k: v for k, v in data.items() if isinstance(v, str)}
                        )
            except Exception:  # noqa: BLE001 - a corrupt cache must not crash setup
                pass
            self._loaded = True

    def save(self) -> None:
        """Persist ONLY real probes — never an offline fallback."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                real = {
                    k: v for k, v in self._cache.items()
                    if k not in self._fallbacks
                }
            self.path.write_text(json.dumps(real, indent=0))
        except Exception:  # noqa: BLE001
            pass

    # --- access --------------------------------------------------------------

    def get(self, key: str) -> str:
        """Return the cached probe for `key`, synthesising + caching on a miss.

        A fallback result is returned but tracked so it is never persisted (and
        re-attempted next run, since a real probe may be synthesised then).
        """
        self.load()
        with self._lock:
            if key in self._cache and key not in self._fallbacks:
                return self._cache[key]
        result = self._synthesize(key)
        with self._lock:
            self._cache[key] = result.text
            if result.is_fallback:
                self._fallbacks.add(key)
            else:
                self._fallbacks.discard(key)
        return result.text

    def prewarm(self, keys: list[str], *, workers: int = 12) -> int:
        """Parallel-synthesise every missing (or fallback-only) probe + persist.

        Run once before a loop so the (sequential) setup phase finds every probe
        already cached and grading starts immediately. Returns the number of keys
        (re)synthesised.
        """
        self.load()
        with self._lock:
            todo = [
                k for k in keys
                if k not in self._cache or k in self._fallbacks
            ]
        if todo:
            with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
                list(ex.map(self.get, todo))
            self.save()
        return len(todo)

    def as_dict(self) -> dict[str, str]:
        """A snapshot copy of the current cache (real + fallback)."""
        with self._lock:
            return dict(self._cache)


__all__ = [
    "ProbeResult",
    "ProbeSynthesizer",
    "ProbeCache",
]
