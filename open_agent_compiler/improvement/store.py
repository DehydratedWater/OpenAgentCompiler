"""Run store — autoloop observability in one database instead of file spray.

Snapshots-as-files (improved/<component>/<target>/<hash>.json plus
.oac/promoted/*.json) stay the *promotion* mechanism — they are what a
registry factory reads at compile time and they diff nicely in git. What
files are bad at is observability: after a fleet run across dozens of
components × targets × rounds, "what happened, what won, and why" is
scattered over hundreds of JSONs. This module records the whole history
in one queryable database:

- every evaluated candidate (definition, metrics, parent lineage, the
  round and target it ran in, whether it survived / won),
- every loop run (component, target, criterion, rounds, winner count),
- every promotion (slot, client bucket, destination path).

`SqliteRunStore` is the stdlib-only default (`sqlite3`, WAL mode, a new
connection per operation so fleet threads can write concurrently).
Construct it from a connection URL — `sqlite:///path/to.db` or a bare
path — via :func:`open_store`; other schemes raise with a pointer to
:class:`RunStore`, the small protocol a Postgres/MySQL-backed store
implements to plug in (register the scheme with
:func:`register_store_scheme`).

Wiring: `IterativeLoop(store=...)` records automatically;
`run_per_target_loops(store=...)` stamps each loop's records with its
target key. The default location convention is
`<project>/.oac/improvement.db` (see :func:`default_store_path`).

Query it with the helpers (`runs()`, `candidates()`, `best_candidate()`)
or plain SQL — the schema is three flat tables designed for ad-hoc
`sqlite3` / Datasette exploration.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from open_agent_compiler.improvement.version import ComponentVersion

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    component_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT,
    criterion TEXT,
    started_at REAL NOT NULL,
    finished_at REAL,
    rounds INTEGER,
    candidate_count INTEGER,
    winner_count INTEGER,
    notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS candidates (
    run_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    component_id TEXT NOT NULL,
    kind TEXT DEFAULT 'agent',
    parent_hash TEXT,
    author TEXT,
    round_index INTEGER,
    definition TEXT NOT NULL,
    metrics TEXT NOT NULL,
    aggregate_score REAL,
    survived INTEGER DEFAULT 0,
    winner INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, content_hash)
);
CREATE TABLE IF NOT EXISTS promotions (
    component_id TEXT NOT NULL,
    slot TEXT,
    client_id TEXT,
    content_hash TEXT,
    metrics TEXT,
    dest_path TEXT,
    promoted_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS compiles (
    compile_id TEXT PRIMARY KEY,
    target TEXT NOT NULL,
    dialect TEXT NOT NULL,
    config TEXT,
    variants TEXT,
    file_count INTEGER,
    files TEXT,
    compiled_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_component
    ON candidates (component_id, aggregate_score);
CREATE INDEX IF NOT EXISTS idx_runs_component ON runs (component_id);
"""


@runtime_checkable
class RunStore(Protocol):
    """What the loops need from a store backend. Implement this (and
    register_store_scheme your URL scheme) to back runs with another DB."""

    def begin_run(
        self, *, component_id: str, kind: str,
        target: str | None = None, criterion: str | None = None,
        notes: str = "",
    ) -> str: ...

    def record_candidate(
        self, run_id: str, version: ComponentVersion, *,
        round_index: int | None = None,
        aggregate_score: float | None = None,
        survived: bool = False, winner: bool = False,
    ) -> None: ...

    def finish_run(
        self, run_id: str, *, rounds: int,
        candidate_count: int, winner_count: int,
    ) -> None: ...

    def record_promotion(
        self, *, component_id: str, slot: str | None,
        client_id: str | None, content_hash: str | None,
        metrics: dict[str, float] | None, dest_path: str,
    ) -> None: ...


@dataclass
class SqliteRunStore:
    """Stdlib SQLite implementation of :class:`RunStore`.

    A new connection per operation + WAL journal mode keeps concurrent
    fleet threads safe without a shared-connection lock. The database
    file is created (with parents) on first use.
    """

    db_path: Path

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ---- RunStore protocol -------------------------------------------

    def begin_run(
        self, *, component_id: str, kind: str,
        target: str | None = None, criterion: str | None = None,
        notes: str = "",
    ) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, component_id, kind, target,"
                " criterion, started_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, component_id, kind, target, criterion,
                 time.time(), notes),
            )
        return run_id

    def record_candidate(
        self, run_id: str, version: ComponentVersion, *,
        round_index: int | None = None,
        aggregate_score: float | None = None,
        survived: bool = False, winner: bool = False,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO candidates (run_id, content_hash, component_id,"
                " kind, parent_hash, author, round_index, definition, metrics,"
                " aggregate_score, survived, winner, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (run_id, content_hash) DO UPDATE SET"
                "  metrics=excluded.metrics,"
                "  aggregate_score=excluded.aggregate_score,"
                "  survived=MAX(candidates.survived, excluded.survived),"
                "  winner=MAX(candidates.winner, excluded.winner)",
                (
                    run_id, version.content_hash, version.component_id,
                    version.kind, version.parent_hash, version.author,
                    round_index,
                    json.dumps(version.definition, default=str),
                    json.dumps(version.metrics, default=str),
                    aggregate_score, int(survived), int(winner), time.time(),
                ),
            )

    def finish_run(
        self, run_id: str, *, rounds: int,
        candidate_count: int, winner_count: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, rounds=?, candidate_count=?,"
                " winner_count=? WHERE run_id=?",
                (time.time(), rounds, candidate_count, winner_count, run_id),
            )

    def record_promotion(
        self, *, component_id: str, slot: str | None,
        client_id: str | None, content_hash: str | None,
        metrics: dict[str, float] | None, dest_path: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO promotions (component_id, slot, client_id,"
                " content_hash, metrics, dest_path, promoted_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (component_id, slot, client_id, content_hash,
                 json.dumps(metrics or {}, default=str),
                 dest_path, time.time()),
            )

    def record_compile(
        self, *, target: str, dialect: str, config: str | None,
        variants: list[str] | None, files: list[str],
    ) -> str:
        """Record one compile's artifacts (not part of the RunStore
        protocol — loops don't need it; CompileScript duck-types it)."""
        compile_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO compiles (compile_id, target, dialect, config,"
                " variants, file_count, files, compiled_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (compile_id, target, dialect, config,
                 json.dumps(variants or []), len(files),
                 json.dumps(files), time.time()),
            )
        return compile_id

    # ---- queries ------------------------------------------------------

    def compiles(self, dialect: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM compiles"
        args: tuple = ()
        if dialect:
            sql += " WHERE dialect=?"
            args = (dialect,)
        sql += " ORDER BY compiled_at"
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        for row in rows:
            row["files"] = json.loads(row["files"])
            row["variants"] = json.loads(row["variants"])
        return rows

    def runs(self, component_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM runs"
        args: tuple = ()
        if component_id:
            sql += " WHERE component_id=?"
            args = (component_id,)
        sql += " ORDER BY started_at"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def candidates(
        self, run_id: str | None = None, *, component_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, args = [], []
        if run_id:
            clauses.append("run_id=?")
            args.append(run_id)
        if component_id:
            clauses.append("component_id=?")
            args.append(component_id)
        sql = "SELECT * FROM candidates"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at"
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]
        for row in rows:
            row["definition"] = json.loads(row["definition"])
            row["metrics"] = json.loads(row["metrics"])
        return rows

    def best_candidate(
        self, component_id: str, *, target: str | None = None,
    ) -> dict[str, Any] | None:
        """Highest-aggregate-score winner for a component (optionally one
        target's runs only)."""
        sql = (
            "SELECT c.* FROM candidates c JOIN runs r ON c.run_id = r.run_id"
            " WHERE c.component_id=? AND c.winner=1"
        )
        args: list[Any] = [component_id]
        if target:
            sql += " AND r.target=?"
            args.append(target)
        sql += " ORDER BY c.aggregate_score DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, tuple(args)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["definition"] = json.loads(out["definition"])
        out["metrics"] = json.loads(out["metrics"])
        return out

    def find_candidate(
        self, component_id: str, hash_prefix: str,
    ) -> dict[str, Any] | None:
        """One recorded candidate by content-hash prefix (highest score on
        ambiguity), decoded like candidates()."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidates WHERE component_id=? AND"
                " content_hash LIKE ? ORDER BY aggregate_score DESC LIMIT 1",
                (component_id, hash_prefix + "%"),
            ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["definition"] = json.loads(out["definition"])
        out["metrics"] = json.loads(out["metrics"])
        return out

    def promotions(self, component_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM promotions"
        args: tuple = ()
        if component_id:
            sql += " WHERE component_id=?"
            args = (component_id,)
        sql += " ORDER BY promoted_at"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]


def version_from_candidate_row(row: dict[str, Any]) -> ComponentVersion:
    """Rebuild a ComponentVersion from a decoded candidates row.

    The content hash is recomputed from the stored definition (they
    match by construction — definitions are stored in canonical JSON
    form); metrics are re-attached for score-aware promotion.
    """
    version = ComponentVersion.of(
        component_id=row["component_id"],
        kind=row.get("kind") or "agent",
        definition=row["definition"],
        author=row.get("author") or "store",
    )
    return version.model_copy(update={"metrics": dict(row.get("metrics") or {})})


# --- URL construction ---------------------------------------------------

StoreFactory = Callable[[str], RunStore]

_SCHEMES: dict[str, StoreFactory] = {}


def register_store_scheme(scheme: str, factory: StoreFactory) -> None:
    """Register a backend for `scheme://...` connection URLs (e.g. a
    postgres-backed RunStore provided by a consumer package)."""
    _SCHEMES[scheme] = factory


def default_store_path(project_root: Path | None = None) -> Path:
    """The conventional store location: <project>/.oac/improvement.db."""
    return (project_root or Path.cwd()) / ".oac" / "improvement.db"


def open_store(url: str | Path | None = None, *, project_root: Path | None = None) -> RunStore:
    """Open a run store from a connection URL, a bare path, or the default.

    - None → SQLite at `<project_root or cwd>/.oac/improvement.db`
    - "sqlite:///path/to.db" or a bare path → SQLite there
    - "<scheme>://..." → the factory registered for that scheme, or a
      ValueError telling you to register_store_scheme / implement RunStore.
    """
    if url is None:
        return SqliteRunStore(default_store_path(project_root))
    if isinstance(url, Path):
        return SqliteRunStore(url)
    if url.startswith("sqlite:///"):
        return SqliteRunStore(Path(url[len("sqlite:///"):]))
    if "://" in url:
        scheme = url.split("://", 1)[0]
        if scheme in _SCHEMES:
            return _SCHEMES[scheme](url)
        raise ValueError(
            f"no run-store backend registered for scheme {scheme!r};"
            " register one with register_store_scheme() (any object"
            " implementing the RunStore protocol works)"
        )
    return SqliteRunStore(Path(url))
