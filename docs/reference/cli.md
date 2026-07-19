# `oac` CLI reference

Every `oac` subcommand with its real arguments and one worked example each.
Most commands take a *factory spec* — `module:callable` returning an
`AgentRegistry` (e.g. `agents:registry`). The current working directory is
prepended to the import path, so specs resolve from a project root without
installing the project.

Global: `oac --version` prints the installed version; `oac <command> --help`
prints the authoritative flag list.

## `oac compile`

Compile a registered configuration to a target directory.

| Argument | Meaning |
|---|---|
| `factory` | `module:callable` returning an `AgentRegistry` |
| `--config NAME` *(required)* | `CompilationConfig` name registered on the registry |
| `--target DIR` *(required)* | output directory for compiled artifacts |
| `--dialect NAME` | output dialect (default `opencode`; list with `oac info --dialects`) |
| `--clean` | delete the target directory before writing |
| `--native-tools` | also emit the harness's native tool-calling form for json-contract tools (see [native tool calling](../guides/native-tools.md)) |
| `--dry-run` | resolve the configuration but write nothing |
| `-v, --verbose` | per-run summary |

```bash
oac compile agents:registry --config prod --target build --dialect pi --clean
```

For programmatic compiles (variants, access profiles, mock profiles,
per-client builds) use `CompileScript` directly — the CLI is a thin adapter
over it.

## `oac info`

Inspect a registry without compiling, or list dialects.

| Argument | Meaning |
|---|---|
| `factory` *(optional)* | registry to introspect; prints agents, templates, configs |
| `--dialects` | list registered output dialects |

```bash
oac info agents:registry
oac info --dialects
```

## `oac test`

Discover and run the tests embedded on agent/tool definitions
(`CapabilityTest`, `ToolTest`, `AgentTest`), emitting one JSONL line per
result. Exit code is 1 if anything failed. See the
[testing guide](../guides/testing.md).

| Argument | Meaning |
|---|---|
| `factory` | registry to test |
| `--config NAME` *(required)* | `CompilationConfig` to compile + test |
| `--results PATH` | JSONL artifact path (default `.oac/test_results.jsonl`) |
| `--force` | bypass the green-hash cache; rerun every discovered test |
| `--filter SUBSTR` | only tests whose name contains this substring |
| `--kind {capability,tool,agent}` | only tests of one kind |
| `--variant NAME` | variant label recorded in artifacts (informational) |
| `-v, --verbose` | per-test pass/fail/skip lines |

```bash
oac test agents:registry --config prod --kind tool --force -v
```

Reruns skip tests whose composite hash matches a previous green run
(`skipped=N` in the summary) — that is the incremental cache, not a failure.

## `oac improve`

Run the iterative improvement loop on one component: mutate, evaluate, keep a
frontier, snapshot round winners. See the
[improvement loop guide](../guides/improvement-loop.md).

| Argument | Meaning |
|---|---|
| `factory` | registry containing the target |
| `--target ID` *(required)* | component to improve (agent slot or registered name) |
| `--config NAME` *(required)* | config that resolves the target agent |
| `--criteria FILE` *(required)* | YAML file describing the `OptimisationCriterion` |
| `--mutators SPECS` | comma-separated: `identity`, `prompt-prefix:<text>`, `prompt-suffix:<text>`, `temperature:<delta>`, `llm-prompt-rewriter` (default `identity`) |
| `--evaluator MOD:FN` | callable taking a `ComponentVersion`, returning a metrics dict; default is a noop returning `{'pass_rate': 1.0}` — replace it for real signal |
| `--max-iters N` | loop rounds (default 3) |
| `--frontier N` | frontier size kept between rounds (default 3) |
| `--output DIR` | snapshot directory (default `improved/`) |

```bash
oac improve agents:registry --target primary --config prod \
    --criteria criteria.yaml --max-iters 5 \
    --mutators identity,llm-prompt-rewriter \
    --evaluator myproject.evaluators:run_oac_test \
    --output improved/
```

## `oac promote`

Stage a winning snapshot so the next compile picks it up (copies it into
`.oac/promoted/`).

| Argument | Meaning |
|---|---|
| `snapshot` | path to a snapshot JSON (typically `improved/<component>/<hash>.json`) |
| `--project DIR` | project root (default: cwd) |
| `--force` | overwrite an existing promotion for the same component |
| `--class LABEL` | promote into a per-model-class slot (`.oac/promoted/<id>__<class>.json`) |
| `--target KEY` | promote into a per-target slot (`pi+fast`, `interactive`, …); load-time resolution is target → class → default |
| `--show` | print the snapshot's metrics + definition instead of promoting |

```bash
oac promote improved/primary/3fa2b1c9.json --class local --force
oac promote improved/summarizer/pi+fast/LATEST.json --target pi+fast
```

## `oac evolve`

Evolve a repo-tailored coding harness: isolated clone (no remotes) →
repo recon → synthesized agents/skills compiled into the workspace →
replay + teacher-gap evolution scaffolding → zip. See
[the evolve guide](../guides/evolve-coding-harness.md).

| Argument | Meaning |
|---|---|
| `repo` | path to the repository to adapt to |
| `--out DIR` | workspace for the isolated copy (default `./evolved_<name>`) |
| `-i, --interactive` | prompt for every option |
| `--dialect NAME` | harness dialect (default `opencode`) |
| `--model M` | model for the synthesized agents |
| `--reference-model M` | stronger teacher model for gap evolution |
| `--commits N` | replay commits for evolution scoring (default 5) |
| `--skills LIST` | developer skill bundles to deploy (default `opencode,claude`) |
| `--zip PATH` / `--no-zip` | package the workspace (default `<out>.zip`) |
| `--native-tools` | compile the harness with native tool calling |

## `oac versions`

Browse, load, unload, and roll back autolooped versions. Reads the run
store at `<project>/.oac/improvement.db` (see the
[optimization targets guide](../guides/optimization-targets.md)).

| Action | Meaning |
|---|---|
| `list <component>` | recorded versions with scores; `*` marks the loaded one |
| `show <component> <hash>` | one candidate in full (definition + metrics) |
| `load <component> <hash>` | write that version into the promoted slot |
| `unload <component>` | remove the promotion — the baseline passes through |
| `rollback <component>` | re-load the previously promoted version |
| `apply-source <component> <file.py>` | rewrite the `system_prompt` literal in the Python source |

Shared flags: `--project`, `--store URL`, `--target KEY`, `--class LABEL`,
`--client ID`, `--force`.

```bash
oac versions list summarizer --target pi+fast
oac versions rollback summarizer --target pi+fast
```

## `oac sync-skills`

Deploy or refresh the framework's developer skill bundles into a project's
`.opencode/skills/` and `.claude/skills/`.

| Argument | Meaning |
|---|---|
| `target` | project directory to refresh |
| `--skills LIST` | comma-separated dialects, subset of `opencode,claude,pi,codex` — the same cross-agent SKILL.md standard (default `opencode,claude`) |
| `--force` | rewrite even when the installed version matches |
| `--check` | write nothing; report fresh/stale/missing and exit 1 on drift |

```bash
oac sync-skills . --skills opencode,claude --check
```

## `oac init`

Scaffold a new project. Covered step by step in
[project scaffolding](../getting-started/project-scaffold.md).

| Argument | Meaning |
|---|---|
| `target` | directory to scaffold into (created if missing) |
| `-i, --interactive` | prompt for every option |
| `--name NAME` | project name (default: directory name) |
| `--template {barebones,web,full,saas-personalized}` | scaffold shape (default `web`) |
| `--llm {anthropic,openai,openrouter,vllm,zai-coding-plan}` | starter provider (default `anthropic`) |
| `--dialect NAME` | dialect the generated `build_agents.py` targets (default `opencode`) |
| `--with-postgres` / `--with-sqlite` / `--with-redis` / `--with-qdrant` / `--with-ollama` | services + starter resources |
| `--with-mcp-server` | agents as MCP tools alongside FastAPI (`web`/`full` only) |
| `--with-telegram-bot` / `--with-cron` / `--cron-events PATH` | delivery + scheduling |
| `--observability {none,langfuse}` / `--proxy {none,nginx,traefik}` | infra add-ons |
| `--skills LIST` | developer skills to emit (`opencode,claude`; empty = none) |
| `--force-overwrite` / `--force-overwrite-all` | refresh framework files (safe) / reset everything (destructive) |
| `--no-uv-sync` | skip the automatic post-scaffold `uv sync` |

```bash
oac init myproject --template full --llm openai --with-cron --skills opencode
```
