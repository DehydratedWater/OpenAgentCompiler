"""`.env.example` generator — declares every env var the scaffold uses."""

from __future__ import annotations

from open_agent_compiler.scaffold.config import LLMProvider, ScaffoldConfig


_LLM_BLOCKS: dict[LLMProvider, str] = {
    "anthropic": (
        "# Anthropic (Claude)\n"
        "ANTHROPIC_API_KEY=your-anthropic-api-key-here\n"
    ),
    "openai": (
        "# OpenAI\n"
        "OPENAI_API_KEY=your-openai-api-key-here\n"
    ),
    "openrouter": (
        "# OpenRouter\n"
        "OPENROUTER_API_KEY=your-openrouter-api-key-here\n"
        "OPENROUTER_BASE_URL=https://openrouter.ai/api/v1\n"
    ),
    "vllm": (
        "# Local vLLM server\n"
        "VLLM_BASE_URL=http://localhost:8000/v1\n"
        "VLLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct\n"
    ),
    "zai-coding-plan": (
        "# Z.AI Coding Plan (GLM-4.5-air etc.)\n"
        "ZAI_API_KEY=your-zai-api-key-here\n"
        "ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4\n"
    ),
}


def render(config: ScaffoldConfig) -> str:
    blocks: list[str] = [
        f"# {config.project_name} environment",
        "# Copy to `.env` and fill in real values. `.env` is gitignored.",
        "",
        _LLM_BLOCKS[config.llm],
    ]
    if config.with_postgres:
        blocks.append(
            "# PostgreSQL (host:5454 host-network or 'db:5432' bridge-network)\n"
            f"POSTGRES_USER={config.project_name}\n"
            f"POSTGRES_PASSWORD={config.project_name}\n"
            f"POSTGRES_DB={config.project_name}\n"
            "DATABASE_URL=postgresql+asyncpg://"
            f"{config.project_name}:{config.project_name}@localhost:5454/{config.project_name}\n"
        )
    if config.with_redis:
        blocks.append(
            "# Redis\n"
            "REDIS_URL=redis://localhost:6379/0\n"
        )
    if config.with_qdrant:
        blocks.append(
            "# Qdrant vector store\n"
            "QDRANT_URL=http://localhost:6333\n"
        )
    if config.with_ollama:
        blocks.append(
            "# Ollama (local LLMs)\n"
            "OLLAMA_HOST=http://localhost:11434\n"
        )
    if config.observability == "langfuse":
        blocks.append(
            "# Langfuse observability\n"
            "LANGFUSE_HOST=https://cloud.langfuse.com\n"
            "LANGFUSE_PUBLIC_KEY=your-langfuse-public-key\n"
            "LANGFUSE_SECRET_KEY=your-langfuse-secret-key\n"
        )
    if config.with_telegram_bot:
        blocks.append(
            "# Telegram bot\n"
            "BOT_TOKEN=your-telegram-bot-token\n"
            "FASTAPI_URL=http://localhost:8002\n"
        )
    if config.template in ("web", "full"):
        blocks.append(
            "# FastAPI service\n"
            "HOST=0.0.0.0\n"
            "PORT=8002\n"
        )
    if config.with_cron:
        blocks.append(
            "# Cron driver — JSON events file location (host path)\n"
            f"CRON_EVENTS={config.cron_events_path}\n"
        )
    return "\n".join(b.rstrip() for b in blocks) + "\n"
