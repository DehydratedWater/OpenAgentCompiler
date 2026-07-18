"""`README.md` generator."""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render(config: ScaffoldConfig) -> str:
    sections: list[str] = [
        f"# {config.project_name}",
        "",
        f"Scaffolded by `oac init --template={config.template}`.",
        "",
        "## Quick start",
        "",
        "1. Copy `.env.example` to `.env` and fill in real values:",
        "   ```bash",
        "   cp .env.example .env",
        "   ```",
        "2. Install dependencies:",
        "   ```bash",
        "   uv sync",
        "   ```",
        "3. Compile starter agents:",
        "   ```bash",
        "   uv run python build_agents.py",
        "   ```",
    ]
    if config.has_web_app:
        sections += [
            "4. Bring services up:",
            "   ```bash",
            "   docker compose -f docker/docker-compose.yml up -d",
            "   ```",
        ]
    if config.is_personalized:
        sections += _personalized_sections(config)
    sections += [
        "",
        "## Layout",
        "",
        "- `build_agents.py` — compiles the registered agents into"
        f" `build/` (dialect: {config.dialect}).",
        "- `agents/` — your agent definitions (Python modules importing"
        " from `open-agent-compiler`).",
        "- `scripts/` — ScriptTool handlers. Copied into `build/scripts/` on compile.",
    ]
    if config.has_web_app:
        sections += [
            "- `docker/` — Dockerfile, docker-compose.yml, entrypoint.sh.",
            "- `app/` — FastAPI service exposing the agents over HTTP.",
        ]
    if config.is_personalized:
        sections += [
            "- `personalization/` — per-client auto-optimization module"
            " (chat→ClientSpec → capability merge → datasource auto-profile →"
            " compile → PersonalizationRun → per-client promotions → serve).",
            "- `app/personalize.py` — FastAPI intake/optimize/serve endpoints.",
            "- `scripts/personalize_client.py` — CLI to run a real per-client loop.",
            "- `config/settings.py` — model refs (env-only) + per-client roots.",
            "- `tests/test_personalization.py` — mocked per-client tests (ship green).",
        ]
    if config.template == "full":
        sections += [
            "- `db/` — SQLAlchemy async session + repositories.",
            "- `migrations/` — Alembic async migrations.",
        ]
    if config.with_cron:
        sections += [
            f"- `{config.cron_events_path}` — JSON events the cron driver"
            " runs against. Edit to schedule agent invocations.",
        ]
    if config.with_sqlite:
        sections += [
            "- `tools/notes_db.py` — ScriptTool that persists notes to"
            " SQLite via the framework's AccessProfile/ResourceHandle path.",
            "- `agents/access_profile.py` — binds the `notes_db` resource"
            " (prod = on-disk file, ci = `:memory:`).",
        ]
    sections += [
        "",
        "## Tests",
        "",
        "Run embedded tests with the framework's test runner:",
        "",
        "```bash",
        "uv run oac test agents:registry --config prod",
        "```",
        "",
        "## Improvement loop",
        "",
        "Iterate on the registered agents against an OptimisationCriterion:",
        "",
        "```bash",
        "# 1) Run the loop — produces snapshots under improved/<component>/",
        "uv run oac improve agents:registry --target starter \\",
        "  --criteria criteria.yaml",
        "",
        "# 2) Promote the winning snapshot",
        "uv run oac promote improved/starter/<hash>.json",
        "",
        "# 3) Recompile — the registry uses `register_with_improvements`",
        "#    so the promoted version merges in transparently",
        "uv run python build_agents.py",
        "```",
        "",
        "For per-model-class tuning (one agent, separate winners per"
        " model class), promote with `--class <name>`; the resolver"
        " picks the matching slot at next compile, falling back to"
        " the default slot when no class-specific promotion exists.",
    ]
    return "\n".join(sections) + "\n"


def _personalized_sections(config: ScaffoldConfig) -> list[str]:
    """The per-client SaaS section: the flow + the moat."""
    return [
        "",
        "## Per-client personalization (the moat)",
        "",
        "A generic agent is a commodity. The defensible product is an agent"
        " **auto-tuned to each customer's private tools + data**. This template"
        " ships that pipeline pre-wired to the framework's per-client"
        " auto-optimization.",
        "",
        "### The flow (chat → spec → merge → optimize → serve)",
        "",
        "```",
        "0. Built-in tools   personalization/builtins.py — the platform base set",
        "1. Elicit (chat)    POST /personalize/intake — client describes their",
        "                    workflow → a validated ClientSpec (teacher via opencode)",
        "2. Capability merge built-in ∪ client MCP ∪ client datasources → one",
        "                    unified per-client surface (merged opencode.json)",
        "3. Datasource       each connected datasource is auto-profiled",
        "   auto-profile     (structure enumerated, conventions inferred) and its",
        "                    derived tools folded into the merged surface",
        "4. Personalized     compile_personalized → a per-client opencode project",
        "   compile          root with the spec-derived prompt overlay + merged tools",
        "5. Per-client loop  PersonalizationRun — GLM teacher (via opencode) rewrites",
        "                    prompt+workflow+tool-use; local-qwen student runs FULL",
        "                    opencode sessions; judge scores vs the client criteria;",
        "                    winners promote to .oac/promoted/<client_id>/",
        "6. Serve            POST /personalize/serve — recompile applying the",
        "                    client's promotions; interactive via LangChain bind,",
        "                    long-running via an opencode session",
        "```",
        "",
        "### Endpoints",
        "",
        "- `POST /personalize/intake` — chat transcript → ClientSpec preview.",
        "- `POST /personalize/optimize` — run the deep-tool-use loop for a client.",
        "- `POST /personalize/serve` — compile + serve the client's tuned agent.",
        "",
        "### Run a real per-client optimization (host, qwen up + opencode authed)",
        "",
        "```bash",
        "PYTHONPATH=/path/to/oac:. ZAI_API_KEY=... \\",
        "  uv run python scripts/personalize_client.py \\",
        "    --client-id acme --chat chat.txt \\",
        "    --mcp-url https://mcp.example/acme/drive \\",
        "    --mcp-tools drive_search,drive_read --max-rounds 3 --target 0.7",
        "```",
        "",
        "The autoloop is **opencode-only** — teacher, judge, and student all route"
        " through opencode (never a raw provider API). Keys live only in a"
        " gitignored `.env`; `opencode.json` uses `env:` refs.",
        "",
        "### Tests ship green",
        "",
        "The per-client flow is covered by fully-mocked tests (no live"
        " opencode/qwen/z.ai):",
        "",
        "```bash",
        "uv run pytest tests/test_personalization.py -q",
        "```",
    ]
