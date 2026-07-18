"""dynamic-extractor skill — compiling agents at runtime, per request."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Dynamic agents compiled at runtime

Most projects in this repo compile their agents once at startup via a
static `registry.py`. A production extraction service proved a
different pattern: **compile a fresh agent on every incoming request**,
because the prompt depends on user-supplied schema + examples.

This skill documents the pattern as a first-class capability so other
SaaS-shaped consumers can use the framework the same way.

## When to use this

- You're building a multi-tenant service where each user defines their
  own extraction target / schema / few-shot examples.
- The compiled prompt body needs to be a function of runtime input
  (schema JSON, sample records, user metadata).
- You want autoresearch on a per-(user, schema) basis, with the
  promoted snapshot stored under the user's namespace.

Skip this pattern when a single static agent + a flexible system
prompt suffices. The compile step costs ~50ms; it's cheap, but it
shouldn't be in your hot path if not needed.

## The factory pattern

The framework's `CompileScript` already accepts any callable returning
an `AgentRegistry`. Build the registry in-memory:

```python
from open_agent_compiler import (
    AgentDefinition, AgentHeader, AgentRegistry,
    AgentToolPermissions as ToolPermissions,
    CompilationConfig, CompileScript, ModelParameters,
    TemplateSlot, TemplateTree,
)


def build_extractor_registry(*, user_id, schema_name,
                              json_schema, examples, model_name):
    slot_name = f"extractor-{schema_name.lower()}"
    agent = AgentDefinition(
        header=AgentHeader(agent_id=slot_name, name=slot_name,
                           description=f"Per-user {schema_name} extractor"),
        usage_explanation_long=f"Extracts {schema_name} records.",
        usage_explanation_short=f"extract {schema_name}",
        system_prompt=_render_prompt(json_schema, examples),
        tool_permissions=ToolPermissions(),  # no tools — pure prompt agent
    )
    reg = AgentRegistry()
    params = ModelParameters(model_name=model_name, temperature=0.0)
    agent_id = reg.register_agent(slot_name, agent, params)
    reg.register_template(TemplateTree(
        name="default",
        slots=[
            TemplateSlot(name="primary", default_agent_id=agent_id),
            TemplateSlot(name=slot_name, default_agent_id=agent_id,
                         also_compile_as_primary=True),
        ],
    ))
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="default"),
    )
    return reg, slot_name


def compile_extractor(*, user_id, job_id, schema_name,
                      json_schema, examples, model_name,
                      agents_root):
    target = agents_root / f"u{user_id}" / f"j{job_id}"
    target.mkdir(parents=True, exist_ok=True)

    def factory():
        reg, _slot = build_extractor_registry(
            user_id=user_id, schema_name=schema_name,
            json_schema=json_schema, examples=examples,
            model_name=model_name,
        )
        return reg

    CompileScript(
        target=target, factory=factory, config="prod",
        clean=True, verbose=False,
    ).run()
    return {
        "agent_dir": str(target),
        "agent_name": f"extractor-{schema_name.lower()}-primary",
        "model": model_name,
    }
```

Always include a `"primary"` slot that aliases the same agent_id, AND
list the named slot with `also_compile_as_primary=True`. That gives
you BOTH `primary.md` (which opencode runs by default if no `--agent`
is passed) AND `<slot>-primary.md` (the explicit name your backend
uses to invoke). Either works.

## The per-job directory convention

Compile into a dir keyed by `(user_id, job_id)`:

```
<AGENTS_ROOT>/
├── u1/
│   ├── j42/
│   │   └── .opencode/agents/extractor-recipe-primary.md
│   └── j43/
│       └── .opencode/agents/extractor-benchmark-primary.md
└── u2/
    └── j17/
        └── .opencode/agents/extractor-procedure-primary.md
```

Why per-job, not per-(user, schema)? Two reasons:

1. Few-shot examples change between jobs. Caching at `(user, schema)`
   means stale prompts ship long after the user refined them.
2. Per-job isolation makes it trivial to keep the `j42` workspace
   alive after the job finishes (for autoresearch replay, audit,
   debugging) without affecting later jobs.

Disk usage is fine — a compiled agent is ~10 KB. 1000 jobs = ~10 MB.

## CRITICAL — opencode does NOT work in /tmp

Verified live: an extractor compiled at `/tmp/agents/u1/j42/` runs
opencode silently to no output. The SAME compiled .md run from
`/home/$USER/programing/.../agents/u1/j42/` works fine.

Reason is not nailed down (probably something about opencode's
internal db / migration / lockfile path resolution), but the
practical rule is: **place AGENTS_ROOT inside a real project
directory, not /tmp or any tmpfs**. In docker, put it on a named
volume mounted under `/data/agents/` — not on `/tmp/`.

## Invoking the compiled agent

Identical to any other compiled agent — `opencode run --agent
<name>-primary` with `XDG_DATA_HOME=<dir>/.opencode/data` and
`PWD=<dir>`, stdin=DEVNULL (the Phase-40 stdin fix). Wrap in a
subprocess from your FastAPI route or background task — the
pattern is proven in a production extraction service.

Parse the JSON event stream's `part.text` fields and extract the
`{"records": [...]}` block — same shape the recipe / benchmark /
procedure schemas follow there.

## Plumbing user context

The system prompt is the only place to inject user information
(opencode's permission YAML has no user field, the runtime has no
user concept). Three options:

1. **Bake it into the prompt** — `"You are an extractor owned by user
   {email}."` Cheap, works for audit-style use.
2. **ENV var** — set `OAC_CTX_USER_ID=42` when spawning opencode. The
   compiled agent's scripts (if any) can read it. The framework's
   `app/agent_runner.py` template already shows this pattern.
3. **MCP tool** — expose `current_user()` as an MCP tool the agent
   can call. Heavy for read-only use; reserve for cases where the
   user identity has to flow into a deferred decision.

Default to option 1 for extraction agents.

## Concurrency model

For a long PDF, fan out page-by-page via `asyncio.Semaphore` —
concurrency 2-4 keeps the model provider happy without burning the
rate limit. The reference implementation:

```python
sem = asyncio.Semaphore(2)
async def _one(page, text):
    async with sem:
        return await extract_from_page(agent_name=..., page=page, ...)

await asyncio.gather(*[_one(p, t) for p, t in pages])
```

Each `extract_from_page` spawns its own `opencode run` subprocess.
opencode handles parallel calls fine (per-session SQLite has WAL
mode), but capping concurrency prevents the host from oversubscribing
the model's rate limit.

## Race: BackgroundTasks + DB writes

When your endpoint creates the job row and queues `add_task(run_job,
job.id)`, **commit explicitly before queueing** — FastAPI's dependency
teardown commits, but the background task can fire before that commit
in some configurations:

```python
session.add(job)
await session.commit()     # ← must be explicit, not implicit
await session.refresh(job)
background.add_task(run_job_async, job.id)
```

Without the explicit commit, the background task does
`session_scope().get(Job, id)` → returns None → silent early exit.
You'll see "job loaded=None" with no other symptoms. Hard to debug;
documenting it here so future-you saves the hour.

## Why no tools in the extractor

`ToolPermissions()` — read=False, write=False, edit=False, mcp=False.
A pure-prompt extractor doesn't need to write files (the caller
captures stdout); doesn't need bash (no commands to run); doesn't need
Task (no subagents to spawn). Stripping permissions eliminates a class
of prompt-injection escapes — even if a user-supplied example tries to
trick the model into calling a tool, the runtime denies it.

## See also

- `authoring-agents` — the `AgentDefinition` model + dual-compile
  pattern this skill assumes.
- `sandboxed-scripting` — write-only-into-sandbox pattern for cases
  where the EXTRACTED data should drive subsequent script generation.
- `improvement-loop` — to autoresearch a dynamic extractor on edge
  cases the user surfaces.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="dynamic-extractor",
        description=(
            "Pattern for compiling agents at runtime per request"
            " (multi-tenant SaaS shape): in-memory AgentRegistry +"
            " per-(user, job) compile dir + AGENTS_ROOT-must-not-be-/tmp."
            " Proven in a production extraction service."
        ),
        body_markdown=BODY,
        tools_hint=(
            "CompileScript", "AgentRegistry", "AgentDefinition",
            "TemplateSlot.also_compile_as_primary",
        ),
    )
