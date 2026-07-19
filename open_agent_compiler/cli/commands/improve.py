"""`oac improve` — run the iterative improvement loop against an agent.

Composes:
- A registered AgentRegistry (resolved via the same factory spec
  pattern as `oac compile/test`).
- A target component id (agent slot or registered name).
- An OptimisationCriterion YAML file.
- A list of mutators (named, bundled or user-supplied).
- An Evaluator callable (user-supplied via --evaluator
  `module:callable`, falling back to a noop default for plumbing checks).
- An output directory for the JSON snapshots of round winners.

Usage:
    oac improve <factory> \\
        --target persona/orch --config prod \\
        --criteria criteria.yaml --max-iters 5 \\
        --mutators identity,prompt-prefix:CRITICAL: \\
        --evaluator myproj.evaluators:run_oac_test \\
        --output improved/
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any, Callable

import yaml

from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.loop import IterativeLoop
from open_agent_compiler.improvement.mutators import (
    IdentityMutator,
    LLMPromptRewriter,
    Mutator,
    PromptPrefixMutator,
    PromptSuffixMutator,
    TemperatureMutator,
)
from open_agent_compiler.improvement.snapshot import write_round_winners
from open_agent_compiler.improvement.version import ComponentVersion


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "improve",
        help="Run the iterative improvement loop on a target component.",
    )
    p.add_argument(
        "factory",
        help="module:callable returning an AgentRegistry.",
    )
    p.add_argument(
        "--target", required=True,
        help="Component id to improve (agent slot or registered name).",
    )
    p.add_argument(
        "--config", required=True,
        help="CompilationConfig name (resolves which agent to target).",
    )
    p.add_argument(
        "--criteria", type=Path, required=True,
        help="YAML file describing the OptimisationCriterion.",
    )
    p.add_argument(
        "--mutators", default="identity",
        help=(
            "Comma-separated mutator specs. Bundled names: identity,"
            " prompt-prefix:<text>, prompt-suffix:<text>, temperature:<delta>,"
            " llm-prompt-rewriter. Default: 'identity' (control run)."
        ),
    )
    p.add_argument(
        "--evaluator", default=None,
        help=(
            "module:callable taking a ComponentVersion and returning a"
            " metrics dict. Default: noop evaluator that returns"
            " {'pass_rate': 1.0} — replace with a real eval to drive"
            " the loop with measured signal."
        ),
    )
    p.add_argument(
        "--max-iters", type=int, default=3,
        help="Maximum number of loop rounds (default: 3).",
    )
    p.add_argument(
        "--frontier", type=int, default=3,
        help="Frontier size kept between rounds (default: 3).",
    )
    p.add_argument(
        "--output", type=Path, default=Path("improved"),
        help="Directory for JSON snapshots (default: ./improved).",
    )
    p.add_argument(
        "--store", nargs="?", const="default", default=None,
        help=(
            "Record the run (rounds/candidates/winners) in the run store."
            " Pass a URL ('sqlite:///path.db'), or no value for the"
            " default .oac/improvement.db — browse with `oac versions`."
        ),
    )


def _parse_mutators(spec: str) -> list[Mutator]:
    mutators: list[Mutator] = []
    for token in (s.strip() for s in spec.split(",") if s.strip()):
        if ":" in token:
            name, value = token.split(":", 1)
        else:
            name, value = token, ""
        if name == "identity":
            mutators.append(IdentityMutator())
        elif name == "prompt-prefix":
            if not value:
                raise ValueError("prompt-prefix mutator needs a 'prompt-prefix:<text>' argument")
            mutators.append(PromptPrefixMutator(value))
        elif name == "prompt-suffix":
            if not value:
                raise ValueError("prompt-suffix mutator needs a 'prompt-suffix:<text>' argument")
            mutators.append(PromptSuffixMutator(value))
        elif name == "temperature":
            try:
                delta = float(value)
            except ValueError as exc:
                raise ValueError(
                    f"temperature mutator needs a float delta, got {value!r}"
                ) from exc
            mutators.append(TemperatureMutator(delta))
        elif name == "llm-prompt-rewriter":
            mutators.append(LLMPromptRewriter())
        else:
            raise ValueError(
                f"unknown mutator {name!r}; bundled: identity / prompt-prefix /"
                " prompt-suffix / temperature / llm-prompt-rewriter"
            )
    return mutators


def _load_criterion(path: Path) -> OptimisationCriterion:
    raw = yaml.safe_load(path.read_text())
    return OptimisationCriterion.model_validate(raw)


def _load_evaluator(spec: str | None):
    if spec is None:
        return lambda version: {"pass_rate": 1.0}
    if ":" not in spec:
        raise ValueError(f"evaluator spec must be 'module:callable', got {spec!r}")
    mod_name, attr = spec.rsplit(":", 1)
    fn = getattr(importlib.import_module(mod_name), attr)
    if not callable(fn):
        raise ValueError(f"{spec} is not callable")
    return fn


def _baseline_version(
    factory, config_name: str, target: str,
) -> ComponentVersion:
    registry = factory()
    resolved = registry.resolve_config(config_name)
    variant = None
    for slot, v in resolved.items():
        # Match either slot name or the agent's logical name.
        if slot == target or v.agent_definition.header.name == target:
            variant = v
            break
    if variant is None:
        raise ValueError(
            f"target {target!r} not present in resolved tree for config"
            f" {config_name!r}. Available slots: {sorted(resolved)}"
        )
    return ComponentVersion.of(
        component_id=target,
        kind="agent",
        definition=json.loads(variant.agent_definition.model_dump_json()),
        author="human",
    )


def handle(
    args: argparse.Namespace,
    load_factory: Callable[[str], Callable[[], Any]],
) -> int:
    factory = load_factory(args.factory)
    baseline = _baseline_version(factory, args.config, args.target)
    criterion = _load_criterion(args.criteria)
    mutators = _parse_mutators(args.mutators)
    evaluator = _load_evaluator(args.evaluator)

    store = None
    if args.store is not None:
        from open_agent_compiler.improvement.store import open_store
        store = open_store(None if args.store == "default" else args.store)

    loop = IterativeLoop(
        baseline=baseline, mutators=mutators, criterion=criterion,
        evaluator=evaluator,
        max_rounds=args.max_iters, frontier_size=args.frontier,
        store=store, run_notes=f"oac improve {args.target}",
    )
    result = loop.run()
    snapshot_paths = write_round_winners(
        result.winners, args.output, run_label=criterion.name,
    )

    print(
        f"oac improve: target={args.target!r} rounds={len(result.rounds)}"
        f" winners={len(result.winners)} snapshots={len(snapshot_paths)}"
    )
    for v in result.winners:
        score = sum(v.metrics.values()) / max(1, len(v.metrics))
        print(
            f"  {v.author:30s} hash={v.content_hash[:8]}… "
            f"avg_metric={score:.3f}"
        )
    return 0
