"""`oac versions` — browse, load, unload, and roll back autolooped versions.

The improvement pipeline produces versions in two places: the run store
(the database holding every candidate a loop ever evaluated) and
snapshot files (the finalized JSON exports). "Loading" a version means
writing it into `.oac/promoted/<id>[__<slot>].json` — the single
version-controlled JSON the next compile merges; "unloading" removes
that file so the Python baseline passes through again; "rollback"
re-loads the previously promoted version using the store's promotion
history.

    oac versions list orch                     # every recorded version
    oac versions list orch --target pi+fast    # one target's runs
    oac versions show orch 3fa9c2             # one version in full
    oac versions load orch 3fa9c2 --target pi+fast
    oac versions unload orch --target pi+fast
    oac versions rollback orch --target pi+fast
    oac versions apply-source orch agents.py  # rewrite the Python prompt

All subcommands read the store at `.oac/improvement.db` under --project
by default; --store accepts a connection URL ('sqlite:///…').
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable

from open_agent_compiler.improvement.snapshot import (
    Snapshot,
    _promoted_dir,
    _promoted_filename,
    find_promoted_snapshot,
)
from open_agent_compiler.improvement.store import (
    SqliteRunStore,
    default_store_path,
    open_store,
    version_from_candidate_row,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "versions",
        help="Browse, load, unload, and roll back autolooped versions.",
    )
    p.add_argument(
        "action",
        choices=["list", "show", "load", "unload", "rollback", "apply-source"],
        help="What to do.",
    )
    p.add_argument("component", help="Component id (agent/tool/skill name).")
    p.add_argument(
        "ref", nargs="?", default=None,
        help=(
            "For show/load: a content-hash prefix. For apply-source: the"
            " path of the Python file whose system_prompt to rewrite."
        ),
    )
    p.add_argument("--project", type=Path, default=Path.cwd(),
                   help="Project root (default: cwd).")
    p.add_argument("--store", default=None,
                   help="Run-store URL (default: <project>/.oac/improvement.db).")
    p.add_argument("--target", default=None,
                   help="Per-target slot key ('pi+fast', 'interactive', …).")
    p.add_argument("--class", dest="model_class", default=None,
                   help="Per-class slot label.")
    p.add_argument("--client", dest="client_id", default=None,
                   help="Per-client promotion bucket.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite an existing promotion on load/rollback.")


def _store_for(args: argparse.Namespace) -> SqliteRunStore | None:
    if args.store:
        store = open_store(args.store, project_root=args.project)
        return store if isinstance(store, SqliteRunStore) else store  # type: ignore[return-value]
    path = default_store_path(args.project)
    if not path.exists():
        return None
    return SqliteRunStore(path)


def _slot(args: argparse.Namespace) -> str | None:
    return args.target or args.model_class


def _promoted_path(args: argparse.Namespace, component: str) -> Path:
    return _promoted_dir(args.project, args.client_id) / _promoted_filename(
        component, _slot(args),
    )


def _write_promotion(
    args: argparse.Namespace, component: str, row: dict[str, Any],
    store: SqliteRunStore | None,
) -> Path:
    version = version_from_candidate_row(row)
    dest = _promoted_path(args, component)
    if dest.exists() and not args.force:
        raise FileExistsError(f"{dest} already exists; pass --force to replace")
    dest.parent.mkdir(parents=True, exist_ok=True)
    snap = Snapshot(version=version, notes=f"oac versions load {version.content_hash[:12]}")
    dest.write_text(snap.model_dump_json(indent=2))
    if store is not None:
        store.record_promotion(
            component_id=component, slot=_slot(args), client_id=args.client_id,
            content_hash=version.content_hash, metrics=dict(version.metrics),
            dest_path=str(dest),
        )
    return dest


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def handle(
    args: argparse.Namespace,
    load_factory: Callable[[str], Callable[[], Any]],
) -> int:
    store = _store_for(args)
    component = args.component

    if args.action == "list":
        if store is None:
            print("oac versions: no run store found (looked for"
                  f" {default_store_path(args.project)}); run loops with"
                  " store=open_store() to record history")
            return 2
        current = find_promoted_snapshot(
            component, args.project, model_class=args.model_class,
            client_id=args.client_id, target=args.target,
        )
        current_hash = current.version.content_hash if current else None
        rows = store.candidates(component_id=component)
        if args.target:
            run_targets = {r["run_id"]: r.get("target") for r in store.runs(component)}
            rows = [r for r in rows if run_targets.get(r["run_id"]) == args.target]
        if not rows:
            print(f"oac versions: no recorded versions for {component!r}")
            return 0
        print(f"{'hash':<14}{'round':>5}  {'score':>7}  {'flags':<8}{'when':<18}author")
        for r in rows:
            flags = "".join((
                "W" if r["winner"] else "",
                "S" if r["survived"] else "",
                "*" if r["content_hash"] == current_hash else "",
            ))
            score = r["aggregate_score"]
            print(
                f"{r['content_hash'][:12]:<14}"
                f"{(r['round_index'] if r['round_index'] is not None else '-'):>5}  "
                f"{(f'{score:.3f}' if score is not None else '-'):>7}  "
                f"{flags:<8}{_fmt_ts(r['created_at']):<18}{r['author'] or '-'}"
            )
        print("\nflags: W=winner S=survivor *=currently loaded"
              " (slot: " + (_slot(args) or "default") + ")")
        return 0

    if args.action == "show":
        if store is None or args.ref is None:
            print("oac versions show: needs a run store and a hash prefix")
            return 2
        row = store.find_candidate(component, args.ref)
        if row is None:
            print(f"oac versions: no version {args.ref!r} for {component!r}")
            return 2
        print(json.dumps(
            {k: row[k] for k in
             ("content_hash", "round_index", "aggregate_score", "winner",
              "survived", "author", "metrics", "definition")},
            indent=2, default=str,
        ))
        return 0

    if args.action == "load":
        if store is None or args.ref is None:
            print("oac versions load: needs a run store and a hash prefix")
            return 2
        row = store.find_candidate(component, args.ref)
        if row is None:
            print(f"oac versions: no version {args.ref!r} for {component!r}")
            return 2
        try:
            dest = _write_promotion(args, component, row, store)
        except FileExistsError as exc:
            print(f"oac versions: {exc}")
            return 2
        print(f"oac versions: loaded {row['content_hash'][:12]} → {dest}")
        return 0

    if args.action == "unload":
        dest = _promoted_path(args, component)
        if not dest.exists():
            print(f"oac versions: nothing loaded at {dest}")
            return 2
        dest.unlink()
        if store is not None:
            store.record_promotion(
                component_id=component, slot=_slot(args),
                client_id=args.client_id, content_hash=None,
                metrics=None, dest_path=f"unloaded:{dest}",
            )
        print(f"oac versions: unloaded {dest} (baseline passes through again)")
        return 0

    if args.action == "rollback":
        if store is None:
            print("oac versions rollback: needs the run store's promotion"
                  " history (.oac/improvement.db)")
            return 2
        history = [
            p for p in store.promotions(component)
            if p["slot"] == _slot(args)
            and p["client_id"] == args.client_id
            and p["content_hash"]  # skip unload markers
        ]
        if len(history) < 2:
            print("oac versions rollback: no earlier promotion recorded"
                  f" for {component!r} (slot: {_slot(args) or 'default'})")
            return 2
        previous = history[-2]
        row = store.find_candidate(component, previous["content_hash"])
        if row is None:
            print(f"oac versions rollback: version {previous['content_hash'][:12]}"
                  " is in the promotion history but not among recorded"
                  " candidates — load it from its snapshot file instead")
            return 2
        args.force = True
        dest = _write_promotion(args, component, row, store)
        print(f"oac versions: rolled back to {previous['content_hash'][:12]} → {dest}")
        return 0

    if args.action == "apply-source":
        from open_agent_compiler.improvement.source_apply import (
            SourceApplyError,
            apply_prompt_to_source,
        )
        if args.ref is None:
            print("oac versions apply-source: pass the Python file path as REF")
            return 2
        snap = find_promoted_snapshot(
            component, args.project, model_class=args.model_class,
            client_id=args.client_id, target=args.target,
        )
        if snap is None or "system_prompt" not in snap.version.definition:
            print(f"oac versions apply-source: no promoted system_prompt for"
                  f" {component!r} — load a version first")
            return 2
        try:
            apply_prompt_to_source(
                Path(args.ref), component,
                snap.version.definition["system_prompt"],
            )
        except SourceApplyError as exc:
            print(f"oac versions apply-source: {exc}")
            return 2
        print(
            f"oac versions: wrote promoted prompt into {args.ref} —"
            " consider `oac versions unload` so the promotion doesn't"
            " re-apply on top of the new baseline"
        )
        return 0

    return 2  # pragma: no cover - argparse choices guard this
