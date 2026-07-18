"""docker-and-compose skill — the scaffolded Docker setup and common fixes."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Docker and docker-compose

`oac init --template web|full` scaffolds a Docker setup that runs the
compiled agents alongside the supporting services. This skill covers
the conventions, the most common failure modes, and how to fix them.

## Bringing the stack up

```bash
# First time:
cp .env.example .env  # then edit
uv run python build_agents.py
docker compose -f docker/docker-compose.yml up -d

# Look at what's running:
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f fastapi
```

## Bringing it down

```bash
docker compose -f docker/docker-compose.yml down            # stop containers
docker compose -f docker/docker-compose.yml down -v         # also remove volumes (loses DB data)
```

## Services in the scaffold

The exact set depends on `--template` and `--with-*` flags. Likely
shape:

| Service | Why | Port |
|---------|-----|------|
| `db` (postgres) | Persistence | 5454 host |
| `opencode-web` | Web UI for compiled agents | 4097 host |
| `fastapi` | HTTP entry point | 8002 host |
| `telegram-bot` | (optional) polling bot | — |
| `cron` | (optional) events-driven dispatcher | — |
| `redis` | (optional) cache / queue | 6379 host |
| `qdrant` | (optional) vector store | 6333 host |
| `ollama` | (optional) local LLM | 11434 host |
| `langfuse` | (optional) observability | 3000 host |

## Network mode

The default scaffold uses `network_mode: host` for every service.
Rationale: with bridged networks, agent subprocesses spawned from
inside a container can't reach other services by short DNS names
without extra setup, and `opencode`'s hash-based session filtering
requires the project root path to match between containers. Host
mode side-steps both.

Downsides: ports on the host must be free (the scaffold picks
non-standard ports like 5454 / 4097 / 8002 to minimize collisions).

## Volume permissions

Named volumes (e.g. `oac_venv` for the .venv, `oac_db_data` for
postgres) are created as `root:root` by Docker. Containers run as
UID 1000 (the `appuser` set up in the Dockerfile). Without
intervention, the app gets EACCES on first write.

The scaffolded `docker-entrypoint.sh` fixes this: it runs as root,
chowns the bind/volume targets to `1000:1000`, then drops privileges
via `gosu appuser`. If you change the UID, edit both the Dockerfile
(`useradd -u <UID>`) and the entrypoint chown line.

## XDG_DATA_HOME

The `opencode` CLI writes session data under `$XDG_DATA_HOME` (default
`~/.local/share`). For agent subprocesses to share their sessions with
the web UI, all containers must set the same `XDG_DATA_HOME`. The
scaffold pins this to `./<.opencode/data>` so sessions persist across
container restarts and appear in the web UI.

## API keys

Two conventions:

1. **`.env` file** loaded by docker-compose (`env_file: ../.env`) —
   reaches all containers as environment.
2. **Embedded at compile time** — `build_agents.py` reads
   `ANTHROPIC_API_KEY` from env and writes it into `opencode.json`
   before opencode-web picks it up. This is required because opencode
   doesn't resolve `env:VAR` refs in its config.

Never commit `.env`. It's in `.gitignore` by default.

## Common failure modes

| Symptom | Fix |
|---------|-----|
| `address already in use` | Another process is on that port. Stop it or change the port in compose. |
| `permission denied: /home/.../.venv` | Volume UID mismatch. `docker compose exec fastapi chown -R 1000:1000 /path/to/.venv`. |
| `opencode` runs but the web UI shows no sessions | XDG_DATA_HOME mismatch between containers, or you're running `opencode` from outside the container with a different XDG path. |
| Agent fails with `env:ANTHROPIC_API_KEY` in logs | The key wasn't embedded into opencode.json. Re-run `build_agents.py` with the env var set. |
| `relation "users" does not exist` | Migrations weren't run. `docker compose exec fastapi alembic upgrade head`. |

## Adding a new service

1. Add the service block to `docker/docker-compose.yml`.
2. If it needs a Python client, add the dep to `pyproject.toml` and
   re-`uv sync` (the venv volume picks it up on next container start).
3. If agents need to reach it, add an env var to `.env.example` + read
   it from your ScriptTool / app config.
4. If it needs persistent state, add a named volume.

See also: `providers-and-models`, `variants-and-profiles`.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="docker-and-compose",
        description=(
            "The scaffolded Docker setup — services, network mode, volume"
            " permissions, XDG_DATA_HOME, API-key embedding, and the common"
            " failure modes (with fixes)."
        ),
        body_markdown=BODY,
        tools_hint=("docker compose", "build_agents.py", ".env"),
    )
