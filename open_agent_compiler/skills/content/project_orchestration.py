"""project-orchestration skill — how to build a project end-to-end with oac.

Read this skill FIRST when a user gives you a new goal in a project
scaffolded by `oac init`. It tells you the methodology — what to do
in what order — so you don't skip the autoresearch + composition
loop that the framework is designed to support.
"""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# How to build a project end-to-end with oac

You — the coding agent inside this scaffold — are the one who turns
a goal ("I want an agent that fetches YouTube transcripts and
extracts the takeaways") into a working, tested, optimised, deployed
multi-agent service.

The framework is designed around this loop. **Do not skip steps.**
Each step is cheap if you do it; each is expensive if you skip and
have to backtrack.

## Phase A — Goals, docs, AND a TODO tracker first

**Before writing a single line of code:**

1. **Set up `docs/TASKS.md`** with three sections: Done / Partial /
   Open. Update it as items move. This is your single source of
   truth for "what's left" — without it you will forget what you
   committed to. Also use `TodoWrite` (the in-conversation tracker)
   for the immediate session's working set; `docs/TASKS.md` is the
   persistent record.

2. Write `docs/goals.md`. Capture:
   - The user's high-level objective in plain English.
   - The success criteria — what does "done" look like, measurably?
   - Non-goals — what we are explicitly *not* doing.
   - Side effects expected (DB writes, external API calls, messages
     sent, files produced).

3. Write `docs/architecture.md`. Capture:
   - The components: agents, subagents, tools, skills. Name each.
   - The data flow: who calls who, in what order, with what I/O.
   - Resources required (DB, MCP servers, external APIs).

4. Per-component docs: `docs/agents.md` and `docs/tools.md` with
   one section per component (input / output / side effects /
   dependencies / status). These move from "planned" to "verified"
   as you complete each piece.

5. `docs/autoresearch.md` when you start the optimisation work —
   explicitly distinguish what's been measured vs what's still a
   placeholder criterion. Be honest about this; keyword-counting
   isn't optimisation.

**Any future modification updates these files BEFORE touching code.**
This is non-negotiable. The docs are the contract; the code is the
implementation. If you find yourself changing code without first
updating docs, stop and update the docs.

**The TODO list is also non-negotiable.** Without it you will tell
the user "shipped X" when you actually shipped a placeholder version
of X. Track it.

## Phase B — Decompose into explicit components

Every component must have:
- A `component_id` (the lookup key for promotions, snapshots, tests).
- A clearly-defined input schema (Pydantic).
- A clearly-defined output schema (Pydantic).
- A list of side effects (DB writes, external calls).
- Optionally, dependencies on other components (subagents, tools).

Write `agents/decomposition.md` listing each component with these
five fields. For the transcripts example:

```
tool: yt_transcript_fetcher
  in: { video_id: str }
  out: { segments: list[{start, end, text}] }
  side_effects: outbound HTTPS to YouTube
  deps: none

tool: transcript_chunker
  in: { segments: list[...] }
  out: { chunks: list[{start, end, text}] }
  side_effects: none
  deps: none

tool: notes_db_writer
  in: { video_id, chunk: dict, takeaway: str }
  out: { ok: bool, row_id: int }
  side_effects: INSERT into postgres (or sqlite)
  deps: notes_db resource

agent: take_aways_extractor
  in: { chunks: list[...] }
  out: { takeaways: list[str] }
  side_effects: calls llm
  deps: none

agent (composite): yt_ingest_orchestrator
  in: { video_id: str }
  out: { takeaways: list[str], rows_written: int }
  side_effects: HTTPS to YouTube, DB writes
  deps: yt_transcript_fetcher, transcript_chunker, take_aways_extractor, notes_db_writer
```

## Phase C — Mocks and schemas BEFORE handlers

For each component, set up the test substrate before the handler:

1. **Tools**: write the `ToolDefinition` with the Pydantic Input/Output
   schemas and a `MockResponse(kind="fixed", fixed_output=...)`. The
   real handler can be a stub that raises NotImplementedError.
2. **DB-backed tools**: write the schema in `migrations/versions/`
   (Alembic if postgres, raw `CREATE TABLE` if sqlite). Mount the DB
   under the `ci` AccessProfile as `:memory:` (sqlite) or a test
   container (postgres). Run `alembic upgrade head` (or the sqlite
   bootstrap) before tests.
3. **Agents**: write the `AgentDefinition` with a placeholder
   `system_prompt`. Define what tools it can call via `skills` and
   `extra_tools`.
4. **Composite agents**: write the `subagents=[...]` list pointing
   at the leaf agents and tools.

This is the moment to use `MockResponse(kind="sequence", ...)` and
`MockResponse(kind="stateful_callable", ...)` for any tool that's
called multiple times in a scenario — e.g. a monitoring agent that
checks DB state across turns. Without sequenced mocks the multi-turn
tests cannot exercise the real behaviour.

## Phase D — Write tests for each component

Each component gets `tool_tests` / `agent_tests` / `capability_tests`
embedded directly on its definition. **Tests exist before any
optimisation; the loop scores against them.**

For the transcript example:

```python
yt_transcript_fetcher = ToolDefinition(
    ...,
    mock=MockResponse(kind="fixed", fixed_output={
        "segments": [{"start": 0, "end": 5, "text": "hello"}],
    }),
    tool_tests=[
        ToolTest(name="happy-path",
                 input={"video_id": "abc"},
                 evaluators=(
                     JsonPathEvaluator(path="segments.0.text", expected="hello"),
                 )),
        ToolTest(name="rejects-empty-id",
                 input={"video_id": ""},
                 evaluators=(SubstringEvaluator(needle="invalid"),)),
    ],
)
```

For the composite, write a multi-turn `AgentTest`:

```python
yt_ingest_orchestrator = AgentDefinition(
    ...,
    agent_tests=[
        AgentTest(
            name="end-to-end-ingest",
            turns=(
                Turn(prompt="Ingest video abc123",
                     expected_tool_calls=("yt_transcript_fetcher",
                                          "transcript_chunker",
                                          "notes_db_writer")),
                Turn(prompt="What did we ingest?",
                     evaluators=(SubstringEvaluator(needle="rows_written"),)),
            ),
            access_profile="ci",
            mock_profile="ingest-mocks",
        ),
    ],
)
```

## Phase E — Optimise each leaf component first

Run `oac improve` against each tool / agent that has its own
component_id BEFORE composing. The composite inherits the
improvements via `register_with_improvements`; if you optimise the
composite first, every leaf change invalidates the composite's
score.

```bash
# For each leaf in topological order:
uv run oac improve agents:registry --target take_aways_extractor \\
    --criteria criteria.yaml --max-iters 5
uv run oac promote improved/take_aways_extractor/<hash>.json

uv run oac improve agents:registry --target transcript_chunker \\
    --criteria criteria.yaml --max-iters 5
uv run oac promote improved/transcript_chunker/<hash>.json

# ... repeat for every tool with non-trivial behaviour
```

Each promotion is one PR-sized change. Inspect the diff before
promoting; the snapshots are JSON and easy to read.

## Phase F — Optimise the composite

Only after every leaf is at its desired score, optimise the
composite. The criterion here is different: per-leaf criteria focus
on the leaf's output; composite criteria focus on whole-chain
properties — `tool_failure_rate` ≤ 5%, multi-turn task completion,
side-effect correctness.

```bash
uv run oac improve agents:registry --target yt_ingest_orchestrator \\
    --criteria criteria.composite.yaml --max-iters 5
uv run oac promote improved/yt_ingest_orchestrator/<hash>.json
```

## Phase G — Compile and ship

```bash
uv run python build_agents.py
```

The registry's `register_with_improvements` calls have already
merged every promotion into the compiled output. `build/.opencode/`
is your shippable artifact. The Dockerfile + docker-compose +
FastAPI service shipped by `oac init` deploy it as a microservice:
the FastAPI receives `POST /agents/{name}/run` requests, the cron
service fires scheduled `events.json` entries, opencode-server runs
the actual model calls. The runs table records every invocation
with its tool_calls and failure count.

## Anti-patterns — things to avoid

- **Skipping Phase A.** Writing code first and "documenting later"
  always means the docs never get written. Treat docs as the spec.
- **Optimising the composite before the leaves.** Composite scores
  are noisy when leaves keep changing; you waste compute exploring
  a moving target.
- **Hand-writing prompts without measurable tests.** The framework
  cannot optimise what you cannot measure; an unmeasured prompt
  rots when the model behind it changes.
- **Hard-coding values instead of binding through AccessProfile.**
  When tests run under the `ci` profile the bindings switch to
  in-memory; hard-coded `/var/data/...` paths break every test.
- **One giant agent with twenty tools.** The framework's superpower
  is composability; decompose into 3-5 small agents each doing one
  thing well, then compose them.

## Patterns discovered building real projects

Captured from the first external consumer (a media-tracking
production project). Read these BEFORE you hit the same
problems.

### ScriptTool's `execute()` is sync — never call it from an
async caller

ScriptTool's contract is `def execute(self, input) -> output`. The
runtime calls `asyncio.run()` *inside* execute() when the tool
itself needs async work. That breaks if you call `tool.execute(...)`
from a coroutine — you'll get "asyncio.run() cannot be called from
a running event loop". Smoke tests and CLI drivers should be sync
top-level; the async loop is the tool's internal detail.

### Stub `session_scope` for smoke tests without a DB

When you want an end-to-end smoke test against real network services
but don't want to depend on docker-compose for the DB, monkey-patch
`db.session.session_scope` with a context manager that yields an
in-memory `_StubSession`. The smoke test for `searchapi.py` in the
YT project shows the shape — a `_CACHE` dict + a `_StubSession`
class with one `execute()` method that fakes the cache_get / cache_put
queries. Keeps the smoke test runnable in one command (`uv run python
tools/_smoke_test_*.py`) without spinning up postgres.

### Start autoresearch from a *deliberately-weak* baseline

If you point `IterativeLoop` at the already-good registered prompt,
the baseline scores 1.0 on most criteria and no mutator has signal
to improve. Pattern: in your `improve_<agent>.py` driver, take the
registered AgentDefinition, then overwrite *just* `system_prompt`
with a stripped-down version, and run the loop against that. The
mutators (PromptPrefix / LLMPromptRewriter) get exercised and the
winners-vs-baseline delta is visible. The registered prompt stays
untouched in the source.

### Use `result.best(metric=...)` to pick a winner

`IterativeLoop.run()` returns a `LoopResult` whose `winners` is a
flat list. Use `result.best()` (defaults to ranking by `score_floor`)
or `result.best(metric="prompt_coverage")` to get the single
highest-scoring version. Don't iterate `result.rounds` to find it —
the framework already aggregated Pareto-frontier survivors in
`winners`.

### Promote then re-compile to close the loop

```bash
uv run oac promote improved/<component>/<hash>.json
uv run python build_agents.py
```

If the promoted snapshot's `system_prompt` matches what your
registered agent already says, the compile will report `wrote 0
file(s)` — that's correct: `register_with_improvements` saw no
diff. To verify the merge actually applied, change the baseline
prompt deliberately first, then check the compiled `.opencode/agents/
<name>.md` contains the promoted text.

### Stash external API tokens in `.env`, never in `.env.example`

The scaffold gitignores `.env`. Real keys (SearchAPI, model
providers) belong in `.env` only; `.env.example` ships placeholders.
If you slip up and commit a real key, `git reset --soft HEAD~1` is
the cleanest fix when the repo has no remote — rewrite the commit
without the key. Don't rely on later scrub commits; the key remains
in git history at the bad SHA.

### Provider-qualified model names

Opencode requires `provider/model_id` for routing. The scaffold's
`_default_model()` returns the qualified name (e.g.
`zai-coding-plan/glm-4.5-air`). When you add new agents in your
own registry, follow the same convention — a bare `glm-4.5-air`
will fail at runtime.

### asyncpg + SQLAlchemy: `:name::jsonb` parses wrong

When writing repository queries with `sqlalchemy.text(...)` against
asyncpg, the postgres cast operator `::` collides with SQLAlchemy's
`:name` parameter syntax. `INSERT INTO t(x) VALUES (:payload::jsonb)`
fails with "syntax error at or near :". Use explicit
`CAST(:payload AS jsonb)` instead — applies to every postgres cast
when you're using parameter binding. The error message is unhelpful;
if you see "syntax error at or near :" in a JSONB INSERT, this is it.

### `set -a; source .env; set +a` for one-shot CLI invocations

`uv run python tool.py` does NOT auto-load `.env`. When you want to
invoke a ScriptTool directly from the shell (smoke tests, ad-hoc
queries), prepend `set -a && source .env && set +a &&` — that
exports every `KEY=value` line into the environment. The FastAPI
service and the agent runner read `.env` via python-dotenv or the
runtime's env loader; only direct CLI hits need this wrapper.

### Compose `network_mode: host` exposes ports without a `ports:` block

The scaffold's db service uses `network_mode: host` + `PGPORT=5454`
so postgres listens on the host's 5454 directly. There's no
`ports:` block — `docker ps` shows empty PORTS but `psql -h
localhost -p 5454` still connects. Don't add a `ports:` line; with
host networking it's redundant and may silently fail to attach.

### Every AgentTest needs an explicit `mock_profile`

Without `mock_profile="..."` set on each AgentTest, the runner
falls back to the tool's default `mock` (when one is set) or tries
the real handler. For deterministic embedded tests that ship with
the project, always: (1) `reg.register_mock_profile(MockProfile(
name="ci-mocks", responses={...}))` once, and (2) reference that
name from every embedded test's `mock_profile` field.

### `OAC_RESOURCES_JSON` injection vs direct DB session import

Phase 15's `ScriptTool.execute(input, resources)` reads
`OAC_RESOURCES_JSON` when set. The compile pipeline doesn't
auto-populate it per invocation, so two patterns are both valid:
  - **Direct**: `from db.session import session_scope` inside the
    handler. Matches `tools/searchapi.py` in the YT project.
  - **Resources kwarg**: set `OAC_RESOURCES_JSON` yourself (e.g.,
    in tests). Example 33 (`33_sqlite_resources/`) shows this.

### `oac init --force-overwrite` is destructive of user files

`--force-overwrite` rewrites every scaffold-owned file unconditionally,
including `agents/registry.py`, `pyproject.toml`, and `.env.example`
— files the user almost certainly customised. There's no per-file
manifest yet distinguishing framework-owned from user-owned. If
you need to refresh just one generated file (e.g., to pick up a
framework fix to `db/repositories.py`), the pragmatic path is:
  1. `git stash`
  2. `oac init . --force-overwrite ...`
  3. `git checkout -- <files you want to keep>`
  4. `git stash pop` if needed.
Or just write the file from the framework directly into the user
project. Track this as a framework gap for a later phase.

### Slot-name drives agent mode — and the dual-compile escape hatch

`AgentVariant.agent_mode` gets overwritten by `resolve_config`:
slot named `"primary"` → `mode: primary`; any other slot →
`mode: subagent`. So a subagent CAN'T be invoked directly via
`opencode run --agent <name>` (opencode falls back to default).

**Fix shipped in Phase 31**: set
`TemplateSlot(name=..., default_agent_id=..., also_compile_as_primary=True)`.
The compiler then emits BOTH `<name>.md` (subagent for Task
delegation) AND `<name>-primary.md` (primary mode, callable
directly via `opencode run --agent <name>-primary` or via
`opencode_manager.py run --agent <name>-primary` from other
primaries). Used by every worker in a production consumer.

### "wrote 0 file(s)" on `python build_agents.py` after `oac promote`

Two distinct meanings, same message today:
  1. The promoted snapshot matches the registered prompt — nothing
     to merge. Correct behaviour.
  2. The compile was a re-run and nothing changed.
To tell them apart: `git diff build/.opencode/agents/<name>.md`
after the rebuild — if non-empty, the promotion took effect.

### Subagents cannot be invoked directly via `opencode run --agent`

opencode prints `agent "<name>" is a subagent, not a primary agent.
Falling back to default agent` and routes through the default
primary's Task tool. That's correct for production but breaks
autoresearch evaluators (can't compile-and-score an isolated
subagent). Fix: set `TemplateSlot.also_compile_as_primary=True` on
every slot that needs direct invocation — the compiler emits BOTH
`<name>.md` (subagent) and `<name>-primary.md` (primary). The
primary twin is callable via `opencode run --agent <name>-primary`
AND via `opencode_manager.py run --agent <name>-primary` from other
primaries (the dispatch pattern).

### `write_test_variant_md` quietly accepts the wrong input shape

The helper takes "an AgentDefinition or something AgentDefinition-
shaped". If you pass `version.definition` (a plain dict from a
ComponentVersion), the old version's `getattr()` silently returned
the empty default for `system_prompt` and produced a test variant
with NO prompt body. Agent then ran on opencode's built-in defaults
and produced ad-hoc output that didn't match the evaluator's
contract (`score=None` on every case). Phase 34 fixed this — the
helper now type-dispatches between dict and object. If you see
`score=None` on every eval case, the first sanity check is: does
the temp `.md` written by write_test_variant_md actually contain
your prompt text? `path.read_text()` it.

### Empty-output failure is silent — always check returncode + stderr

When opencode produces zero events with zero stderr (yes, this
happens in rapid-sequential invocations), the evaluator sees no
score and treats it as worst-case error. Always capture stderr +
returncode when invoking opencode programmatically; surface them in
the failure path so debug shows "process ran with rc=0 but emitted
nothing" not "score was None for some reason".

### Sync `subprocess.run` is the right tool for autoresearch eval

For "I want the final output" use cases, `subprocess.run(cmd,
capture_output=True, timeout=600)` is more reliable than the
async StreamingOpencodeRun. A ~105-agent production fleet's
opencode_manager uses `asyncio.create_subprocess_exec +
process.communicate()` — same idea. StreamingOpencodeRun is for
live-progress monitoring (when you want to surface intermediate
events to a UI); for eval loops, simpler is better.

### Full multi-agent orchestration through Task tool actually works

Verified end-to-end: `opencode run --agent primary --format json`
on a registry containing the `research` orchestrator + 6 worker
subagents, given "find 1 channel about X", produces a real channel
row in the database within ~6 minutes. The orchestrator
auto-explored (`ls`, `find`, `--help` on tools) before dispatching
to the right subagent via Task. The compiled Task allowlist +
bash allowlists + DB writes all worked through the chain. Pattern:

```python
proc = subprocess.run(
    ["/path/to/opencode", "run", "--agent", "primary",
     "--log-level", "INFO", "--format", "json",
     "<the full user query>"],
    cwd=build_dir,  # so opencode finds .opencode/agents/
    env={**os.environ,
         "XDG_DATA_HOME": str(build_dir / ".opencode" / "data"),
         "PWD": str(build_dir),
         "DATABASE_URL": db_url, ...},
    capture_output=True, text=True,
    timeout=900,  # 15 min — multi-agent flows need it
)
```

Pre-bring up Postgres + run `alembic upgrade head` before this
call. The 6-min wall-clock kill that bit early tests was just a
short timeout, not an architectural problem; full orchestration
runs end-to-end.

## Where to read more

- `getting-started` — the three commands you'll use every day.
- `authoring-agents` / `authoring-tools` — how to write the
  definitions.
- `writing-tests` — every evaluator kind and how to embed them.
- `improvement-loop` — the autoresearch loop's mutators, criteria,
  per-class promotion.
- `variants-and-profiles` — SplitProfile + VariantSpec for
  multi-variant compiles.
- `docker-and-compose` — the deployment substrate.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="project-orchestration",
        description=(
            "Methodology: how to take a user's goal and turn it into a"
            " tested, optimised, deployed multi-agent service. Read this"
            " FIRST when starting a new project. Covers docs-first,"
            " decomposition, mock-then-handler, test-then-optimise,"
            " leaves-before-composite, ship-via-compose."
        ),
        body_markdown=BODY,
        version="1.1.0",
        tools_hint=(
            "docs/goals.md", "docs/architecture.md",
            "agents/decomposition.md", "build_agents.py",
            "oac test", "oac improve", "oac promote",
            "register_with_improvements",
        ),
    )
