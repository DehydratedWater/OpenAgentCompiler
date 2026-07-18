"""docker/Dockerfile generator — python:3.12-slim + uv + gosu + UID 1000."""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render(config: ScaffoldConfig) -> str:
    return (
        "# syntax=docker/dockerfile:1.7\n"
        "FROM python:3.12-slim\n"
        "\n"
        "ARG APP_USER=appuser\n"
        "ARG APP_UID=1000\n"
        "ARG APP_GID=1000\n"
        "\n"
        "ENV PYTHONUNBUFFERED=1 \\\n"
        "    PYTHONDONTWRITEBYTECODE=1 \\\n"
        "    UV_LINK_MODE=copy\n"
        "\n"
        "RUN apt-get update \\\n"
        "    && apt-get install -y --no-install-recommends \\\n"
        "        ca-certificates curl gosu git \\\n"
        "    && rm -rf /var/lib/apt/lists/*\n"
        "\n"
        "# Install uv\n"
        "RUN curl -LsSf https://astral.sh/uv/install.sh | sh \\\n"
        "    && mv /root/.local/bin/uv /usr/local/bin/uv\n"
        "\n"
        "RUN groupadd --gid ${APP_GID} ${APP_USER} \\\n"
        "    && useradd --uid ${APP_UID} --gid ${APP_GID} -m ${APP_USER}\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "COPY docker/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh\n"
        "RUN chmod +x /usr/local/bin/docker-entrypoint.sh\n"
        "\n"
        'ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]\n'
        'CMD ["bash"]\n'
    )


def render_entrypoint(config: ScaffoldConfig) -> str:
    return (
        "#!/bin/bash\n"
        "# Fix ownership on volumes / bind mounts then drop privileges to appuser.\n"
        "# Docker creates named volumes as root:root, so chown is required before\n"
        "# the appuser-owned process can write into .venv / .opencode/data / etc.\n"
        "set -euo pipefail\n"
        "\n"
        "APP_USER=${APP_USER:-appuser}\n"
        "APP_UID=${APP_UID:-1000}\n"
        "APP_GID=${APP_GID:-1000}\n"
        "\n"
        "# Paths that need fixing — keep idempotent (chown is cheap).\n"
        "for path in /app/.venv /app/.opencode/data /app/.agent_workspace; do\n"
        "    if [ -d \"$path\" ]; then\n"
        "        chown -R \"${APP_UID}:${APP_GID}\" \"$path\" || true\n"
        "    fi\n"
        "done\n"
        "\n"
        'exec gosu "${APP_USER}" "$@"\n'
    )
