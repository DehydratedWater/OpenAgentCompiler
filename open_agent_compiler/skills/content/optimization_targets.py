"""optimization-targets skill — per-harness/per-model adaptation."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Optimization targets — adapt one agent to every harness and model

The framework's promise: define agents ONCE (with tests/benchmarks),
then run autoloops to adapt them to each harness × model they run on —
including the in-process realtime tier. Different targets genuinely
prefer different prompts (terse for small/fast models and pi's
rendering; reasoning room for analytical models and the chat tier).

## Targets

A target is one cell of the adaptation matrix, keyed
`<harness>[+<model_class>]`: `opencode+fast`, `pi+analytical`,
`codex`, `interactive`.

```python
from open_agent_compiler.improvement import (
    OptimizationTarget, run_per_target_loops, targets_from_split_profile,
    build_compiled_evaluator, build_interactive_evaluator, open_store,
)

targets = targets_from_split_profile(["opencode", "pi"], SPLIT)
targets.append(OptimizationTarget(harness="interactive"))

results = run_per_target_loops(
    baseline=baseline, mutators=[...], criterion=criterion,
    targets=targets, evaluator_factory=make_evaluator,
    output=Path("improved"), store=open_store(project_root=ROOT),
)
```

## Evaluators (per target)

- **Compiled harnesses** — `build_compiled_evaluator(probes,
  registry_factory=..., target=..., build_dir=..., config=...,
  agent_name=..., judge=...)`: compiles each candidate with the
  target's dialect, runs probes through the harness runner
  (`get_runner`: opencode / pi / codex / claude), scores with the
  standard evaluators incl. `llm_judge`.
- **The realtime tier** — `build_interactive_evaluator(probes,
  spec_factory, judge=..., client=...)`: runs candidates through
  `run_interactive`. Pass a scripted `client` for the offline gate
  tier; omit for the live provider.
- `registry_factory` / `spec_factory` receive the candidate's mutated
  definition dict and rebuild YOUR registry/spec with it — scaffolded
  projects expose `registry(system_prompt=...)` for exactly this.

## Promotion slots

Resolution at compile time: **target → model_class → default**.

```bash
uv run oac promote improved/<id>/pi+fast/LATEST.json --target pi+fast
```

In the registry factory: `apply_promoted_to_tree(agent,
project_root=ROOT, target="pi+fast", model_class="fast")`.

## Observability + version management

Loop history lives in `.oac/improvement.db` (SQLite; `open_store()`),
NOT in file spray — with a store attached, only the finalized winner
JSON per target is written. Manage what's loaded:

```bash
uv run oac versions list <component> [--target pi+fast]
uv run oac versions load <component> <hash> --target pi+fast
uv run oac versions unload <component> --target pi+fast
uv run oac versions rollback <component> --target pi+fast
uv run oac versions apply-source <component> agents/registry.py
```

`apply-source` rewrites the system_prompt literal in the Python file —
use it when a winner should become the checked-in baseline.

## Native tool calling

`oac compile --native-tools` (or `CompileScript(native_tools=True)`)
emits each harness's native tool form for json-contract tools:
`.opencode/tool/<name>.ts` shims (opencode) or a generated MCP tools
server (`scripts/mcp_tools_server.py` + `.mcp.json` for claude,
`[mcp_servers.oac-tools]` TOML blocks for codex). Bash invocation docs
remain as the fallback.

## Full reference

docs: guides/optimization-targets.md, guides/native-tools.md;
example: examples/85_matrix_live_chat/ (offline-runnable, end to end).
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="optimization-targets",
        description=(
            "Per-target adaptation: run_per_target_loops across"
            " harness × model cells (incl. the interactive tier),"
            " compiled/interactive evaluators, target promotion slots,"
            " the run store, oac versions, and native tool calling."
        ),
        body_markdown=BODY,
        version="1.0.0",
    )
