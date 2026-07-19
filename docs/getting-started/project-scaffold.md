# Project scaffolding with `oac init`

Here you'll generate a complete, Dockerized agent project — registry, compile
script, FastAPI service, cron driver — with one command, then bring it up.
Prerequisites: [`oac` installed](installation.md), Docker with the compose
plugin for step 5, and [uv](https://docs.astral.sh/uv/) on your `PATH`.

## 1. Pick a template and scaffold

```bash
oac init myproject --template web --llm anthropic --with-cron \
    --skills opencode,claude
cd myproject
```

The four templates:

| Template | What you get |
|---|---|
| `barebones` | agent registry + `build_agents.py` compile script, no Docker |
| `web` | + FastAPI service (`app/`) + Docker + optional cron driver |
| `full` | + Telegram bot + Postgres (async SQLAlchemy + Alembic); implies `--with-postgres` |
| `saas-personalized` | per-client auto-optimization SaaS: intake/personalize/serve endpoints, personalization module, mocked per-client tests |

Prefer being asked? `oac init myproject -i` walks through every option
interactively; pressing Enter at each prompt gives the same result as the
flag defaults.

## 2. Know the flags

All verified against `oac init --help`:

| Flag | Meaning |
|---|---|
| `--name NAME` | project name (default: target directory name) |
| `--template {barebones,web,full,saas-personalized}` | scaffold shape (default `web`) |
| `--llm {anthropic,openai,openrouter,vllm,zai-coding-plan}` | provider wired into the starter registry (default `anthropic`) |
| `--dialect NAME` | dialect the generated `build_agents.py` compiles to (default `opencode`; see `oac info --dialects`) |
| `--with-postgres` | Postgres + pgvector + Alembic seed migration |
| `--with-sqlite` | starter SQLite-backed notes ScriptTool + AccessProfile (prod = file, ci = in-memory) |
| `--with-redis` / `--with-qdrant` / `--with-ollama` | extra compose services |
| `--with-mcp-server` | expose compiled agents as MCP tools alongside the REST API (needs `web`/`full`) |
| `--with-telegram-bot` | Telegram bot service |
| `--with-cron` | cron driver container + `cron/events.json` |
| `--cron-events PATH` | where the events JSON lives (default `cron/events.json`) |
| `--observability {none,langfuse}` / `--proxy {none,nginx,traefik}` | optional infra |
| `--skills opencode,claude` | emit developer skill bundles for coding agents working on the scaffold |
| `-i, --interactive` | prompt for every option |
| `--no-uv-sync` | skip the automatic `uv sync` after scaffolding |
| `--force-overwrite` | refresh framework-owned files, **preserving** user-edited ones (tracked in `.oac/scaffold-state.json`) |
| `--force-overwrite-all` | destructive full reset, including your edits |

## 3. What gets generated

For `--template web --with-cron` you get roughly:

```text
myproject/
├── agents/registry.py      # your AgentRegistry factory — edit this
├── build_agents.py         # CompileScript: registry -> build/
├── app/                    # FastAPI service
│   ├── main.py             #   /health /agents /agents/{name}/run /runs/{id} /events/{id}/fire
│   ├── dispatch.py         #   sync / async / fire-and-forget agent dispatch
│   ├── agent_runner.py     #   drives `opencode run` against build/
│   └── models.py           #   AgentRunRequest / AgentRunResult / CronEvent
├── cron/
│   ├── driver.py           # polls events.json, fires matching events at FastAPI
│   └── events.json         # your schedules (ships with disabled examples)
├── docker/                 # Dockerfile, docker-compose.yml, entrypoint
├── run.py                  # uvicorn launcher (HOST/PORT from env, default 8002)
├── .env.example            # provider keys + service settings
├── .oac/scaffold-state.json  # manifest for safe --force-overwrite refreshes
├── .opencode/ .claude/     # developer skills (if --skills given)
└── pyproject.toml          # depends on open-agent-compiler
```

By default init also runs `uv sync` in the new project so dependencies are
installed immediately (silently skipped if uv is missing).

## 4. Configure, compile, test

```bash
cp .env.example .env        # fill in real provider keys
uv run python build_agents.py
uv run oac test agents:registry --config prod
```

`build_agents.py` compiles the starter agents into `build/` for your chosen
dialect. The scaffold's embedded tests run against mocks, so they pass without
credentials — see the [testing guide](../guides/testing.md).

## 5. Bring the stack up

```bash
docker compose -f docker/docker-compose.yml up -d
```

The web template starts three services (all `network_mode: host`):

- **opencode-web** — opencode's web UI serving the compiled agents on port 4097
- **fastapi** — the REST API on port 8002
- **cron** — the event driver (only with `--with-cron`)

Smoke-test it:

```bash
curl http://localhost:8002/health
curl http://localhost:8002/agents
curl -X POST http://localhost:8002/agents/starter/run \
     -H 'content-type: application/json' \
     -d '{"prompt": "hello"}'
```

## 6. The cron → FastAPI → agent flow

Scheduled agent runs are data, not code:

1. `cron/driver.py` reloads `cron/events.json` every 30 s (`CRON_POLL_SECONDS`).
2. Each event is `{id, schedule, agent, prompt, context?, enabled}` with a
   5-field minute-precision cron `schedule`.
3. When a schedule matches the current minute, the driver POSTs the event to
   `POST /events/{id}/fire` on FastAPI (`FASTAPI_URL`, default
   `http://localhost:8002`).
4. FastAPI dispatches the named agent through the same runner as
   `/agents/{name}/run` — i.e. an `opencode run` against `build/`.

So "run the summary agent at 09:00 daily" is a JSON edit:

```json
{
  "id": "daily-summary",
  "schedule": "0 9 * * *",
  "agent": "starter",
  "prompt": "Summarize yesterday's activity.",
  "context": {"trigger": "cron"},
  "enabled": true
}
```

The shipped example events have `"enabled": false` — flip the flag to activate.

## Where to go next

- Replace the starter agent with your own: [Your first agent](first-agent.md)
  and the [agent model](../concepts/agent-model.md)
- Add real tools to the registry: [Tools guide](../guides/tools.md)
- Browse generated trees for every template side by side:
  `examples/90_init_scaffold/` and `examples/91_saas_personalized/` in the
  [examples index](../reference/examples.md)
- Full flag reference: [CLI reference](../reference/cli.md)
