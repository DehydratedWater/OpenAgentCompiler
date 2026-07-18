# 90 init scaffold — `oac init` template variants side-by-side

Programmatically drives `oac init` (well, its underlying
`ScaffoldEngine`) with three different config combos so you can browse
the generated trees and compare templates.

## Run

```bash
uv run python examples/90_init_scaffold/scaffold.py
```

Produces (gitignored) under `examples/90_init_scaffold/generated/`:

| Folder | Template | LLM | Extra services |
|---|---|---|---|
| `barebones/` | `barebones` | anthropic | (none — just compile+CLI) |
| `web-zai/` | `web` | zai-coding-plan | cron driver POSTing to FastAPI |
| `full-stack/` | `full` | zai-coding-plan | postgres + redis + telegram bot + cron + langfuse |

Each project also gets `oac sync-skills` content for opencode + claude
under `.opencode/skills/` + `.claude/skills/` + a `CLAUDE.md` index.

## What you'll see in each scaffold

```
generated/<name>/
  agents/                 — starter registry the user fills in
    registry.py
  build_agents.py         — compile entry-point
  .env.example
  pyproject.toml
  README.md
  .gitignore
  .opencode/skills/...    — developer skill bundles
  .claude/skills/...
  CLAUDE.md

  (web/full only)
  docker/
    Dockerfile
    docker-entrypoint.sh
    docker-compose.yml
  app/
    main.py               — FastAPI with /agents, /agents/{name}/run, /events/{id}/fire
    models.py
    agent_runner.py       — spawns opencode subprocess
  run.py

  (full only)
  cron/
    driver.py             — polls events.json, POSTs to FastAPI
    events.json           — JSON event schedule
```

## Bring up the full stack

```bash
cd examples/90_init_scaffold/generated/full-stack
cp .env.example .env       # then edit — fill in ZAI_API_KEY etc.
uv sync                    # or pip install -e .
uv run python build_agents.py
docker compose -f docker/docker-compose.yml up -d
```

Once up:
- FastAPI: `http://localhost:8002` (POST /agents/{name}/run, /events/{id}/fire)
- opencode web UI: `http://localhost:4097`
- Postgres: `localhost:5454`
- Cron polls `cron/events.json` and POSTs matching events to FastAPI.

## What's exercised

- The whole `ScaffoldConfig` axis matrix:
  - `template ∈ {barebones, web, full}`
  - `llm ∈ {anthropic, zai-coding-plan}` (others available)
  - `with_postgres / with_redis / with_cron / with_telegram_bot`
  - `observability=langfuse`
- The skill emission for both `opencode` and `claude` dialects.
- Per-template file resolution (web template adds Dockerfile + app/;
  full template adds DB + telegram-bot + alembic; cron flag adds
  events.json + driver.py).
- Real Dockerfile (python:3.12-slim + uv + gosu + UID-1000 appuser).
- Real docker-compose (network_mode: host for opencode hash
  consistency, named volumes with entrypoint chown for permission fix,
  XDG_DATA_HOME wiring so opencode web shares sessions).
- cron driver that POSTs to FastAPI (NOT direct subprocess) so the
  agent-invocation logic stays in one place.

The full-stack scaffold maps directly to an e-commerce reference
deployment, modulo the user's own agent definitions.
