"""docker/docker-compose.yml generator — services composed from config flags."""

from __future__ import annotations


from open_agent_compiler.scaffold.config import ScaffoldConfig

PROJECT_PATH_VAR = "${PROJECT_PATH:-..}"


def _fastapi_service(config: ScaffoldConfig) -> str:
    depends_on: list[str] = []
    if config.with_postgres:
        depends_on.append("      db:\n        condition: service_healthy")
    depends_lines = (
        "    depends_on:\n" + "\n".join(depends_on) + "\n"
        if depends_on else ""
    )
    return (
        "  fastapi:\n"
        "    build:\n"
        f"      context: {PROJECT_PATH_VAR}\n"
        "      dockerfile: docker/Dockerfile\n"
        "    network_mode: host\n"
        "    working_dir: /app\n"
        "    volumes:\n"
        f"      - {PROJECT_PATH_VAR}:/app\n"
        f"      - {config.project_name}_venv:/app/.venv\n"
        "    environment:\n"
        "      HOME: /home/appuser\n"
        "      XDG_DATA_HOME: /app/.opencode/data\n"
        "      XDG_CONFIG_HOME: /home/appuser/.config\n"
        "    env_file:\n"
        f"      - {PROJECT_PATH_VAR}/.env\n"
        f"    command: sh -c \"uv sync --frozen && uv run python run.py\"\n"
        f"{depends_lines}"
        "    restart: unless-stopped\n"
    )


def _opencode_web_service(config: ScaffoldConfig) -> str:
    return (
        "  opencode-web:\n"
        "    build:\n"
        f"      context: {PROJECT_PATH_VAR}\n"
        "      dockerfile: docker/Dockerfile\n"
        "    network_mode: host\n"
        "    working_dir: /app/build\n"
        "    volumes:\n"
        f"      - {PROJECT_PATH_VAR}:/app\n"
        f"      - {config.project_name}_venv:/app/.venv\n"
        "    environment:\n"
        "      HOME: /home/appuser\n"
        "      XDG_DATA_HOME: /app/.opencode/data\n"
        "    env_file:\n"
        f"      - {PROJECT_PATH_VAR}/.env\n"
        "    command: >\n"
        "      sh -c \"cd /app && uv sync --frozen && opencode web --hostname 0.0.0.0 --port 4097\"\n"
        "    restart: unless-stopped\n"
    )


def _postgres_service(config: ScaffoldConfig) -> str:
    return (
        "  db:\n"
        "    image: pgvector/pgvector:pg17\n"
        "    network_mode: host\n"
        "    environment:\n"
        f"      POSTGRES_USER: {config.project_name}\n"
        f"      POSTGRES_PASSWORD: {config.project_name}\n"
        f"      POSTGRES_DB: {config.project_name}\n"
        "      PGPORT: 5454\n"
        "    volumes:\n"
        f"      - {config.project_name}_db_data:/var/lib/postgresql/data\n"
        "    healthcheck:\n"
        f"      test: ['CMD', 'pg_isready', '-U', '{config.project_name}', '-p', '5454']\n"
        "      interval: 5s\n"
        "      timeout: 5s\n"
        "      retries: 10\n"
        "    restart: unless-stopped\n"
    )


def _redis_service(config: ScaffoldConfig) -> str:
    return (
        "  redis:\n"
        "    image: redis:7-alpine\n"
        "    network_mode: host\n"
        "    command: redis-server --port 6379\n"
        "    restart: unless-stopped\n"
    )


def _qdrant_service(config: ScaffoldConfig) -> str:
    return (
        "  qdrant:\n"
        "    image: qdrant/qdrant:latest\n"
        "    network_mode: host\n"
        "    volumes:\n"
        f"      - {config.project_name}_qdrant_data:/qdrant/storage\n"
        "    restart: unless-stopped\n"
    )


def _ollama_service(config: ScaffoldConfig) -> str:
    return (
        "  ollama:\n"
        "    image: ollama/ollama:latest\n"
        "    network_mode: host\n"
        "    volumes:\n"
        f"      - {config.project_name}_ollama:/root/.ollama\n"
        "    restart: unless-stopped\n"
    )


def _telegram_bot_service(config: ScaffoldConfig) -> str:
    return (
        "  telegram-bot:\n"
        "    build:\n"
        f"      context: {PROJECT_PATH_VAR}\n"
        "      dockerfile: docker/Dockerfile\n"
        "    network_mode: host\n"
        "    working_dir: /app\n"
        "    volumes:\n"
        f"      - {PROJECT_PATH_VAR}:/app\n"
        f"      - {config.project_name}_venv:/app/.venv\n"
        "    environment:\n"
        "      HOME: /home/appuser\n"
        "    env_file:\n"
        f"      - {PROJECT_PATH_VAR}/.env\n"
        "    command: >\n"
        "      sh -c \"uv sync --frozen && uv run python -m telegram_bot.bot\"\n"
        "    depends_on:\n"
        "      - fastapi\n"
        "    restart: unless-stopped\n"
    )


def _cron_service(config: ScaffoldConfig) -> str:
    return (
        "  cron:\n"
        "    build:\n"
        f"      context: {PROJECT_PATH_VAR}\n"
        "      dockerfile: docker/Dockerfile\n"
        "    network_mode: host\n"
        "    working_dir: /app\n"
        "    volumes:\n"
        f"      - {PROJECT_PATH_VAR}:/app\n"
        f"      - {config.project_name}_venv:/app/.venv\n"
        "    environment:\n"
        "      HOME: /home/appuser\n"
        f"      CRON_EVENTS: /app/{config.cron_events_path}\n"
        "    env_file:\n"
        f"      - {PROJECT_PATH_VAR}/.env\n"
        "    command: >\n"
        "      sh -c \"uv sync --frozen && uv run python -m cron.driver\"\n"
        "    restart: unless-stopped\n"
    )


def _langfuse_service(config: ScaffoldConfig) -> str:
    return (
        "  langfuse:\n"
        "    image: langfuse/langfuse:latest\n"
        "    network_mode: host\n"
        "    env_file:\n"
        f"      - {PROJECT_PATH_VAR}/.env\n"
        "    restart: unless-stopped\n"
    )


def _volumes_section(config: ScaffoldConfig) -> str:
    vols = [f"{config.project_name}_venv:"]
    if config.with_postgres:
        vols.append(f"{config.project_name}_db_data:")
    if config.with_qdrant:
        vols.append(f"{config.project_name}_qdrant_data:")
    if config.with_ollama:
        vols.append(f"{config.project_name}_ollama:")
    body = "\n".join(f"  {v}" for v in vols)
    return f"volumes:\n{body}\n"


def render(config: ScaffoldConfig) -> str:
    services: list[str] = []
    if config.with_postgres:
        services.append(_postgres_service(config))
    services.append(_opencode_web_service(config))
    services.append(_fastapi_service(config))
    if config.with_telegram_bot or config.template == "full":
        services.append(_telegram_bot_service(config))
    if config.with_redis:
        services.append(_redis_service(config))
    if config.with_qdrant:
        services.append(_qdrant_service(config))
    if config.with_ollama:
        services.append(_ollama_service(config))
    if config.observability == "langfuse":
        services.append(_langfuse_service(config))
    if config.with_cron:
        services.append(_cron_service(config))

    services_block = "\n".join(services)
    return (
        "# Generated by oac init. Edit freely.\n"
        "# All services use network_mode: host — see the docker-and-compose skill\n"
        "# for the rationale and how to switch to a bridge network if needed.\n"
        "\n"
        "services:\n"
        f"{services_block}"
        "\n"
        f"{_volumes_section(config)}"
    )
