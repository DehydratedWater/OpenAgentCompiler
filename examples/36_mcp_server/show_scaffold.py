"""Phase 24 — `--with-mcp-server` exposes compiled agents over MCP.

This script scaffolds a `--with-mcp-server` project into a tempdir,
then prints the generated `app/mcp_server.py` + `mcp_server_run.py`
so you can read the wiring without keeping the project around.

Run:

    uv run python examples/36_mcp_server/show_scaffold.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from open_agent_compiler.scaffold.config import ScaffoldConfig  # noqa: E402
from open_agent_compiler.scaffold.engine import ScaffoldEngine  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "demo"
        ScaffoldEngine(config=ScaffoldConfig(
            target=target,
            project_name="yt-mcp-demo",
            template="full",
            llm="anthropic",
            with_mcp_server=True,
            with_postgres=True,
            skills=(),
            force_overwrite=True,
        )).render()

        print("=" * 60)
        print("Generated app/mcp_server.py")
        print("=" * 60)
        print((target / "app" / "mcp_server.py").read_text())

        print("\n" + "=" * 60)
        print("Generated mcp_server_run.py")
        print("=" * 60)
        print((target / "mcp_server_run.py").read_text())

        print("\n" + "=" * 60)
        print("pyproject.toml dependency added")
        print("=" * 60)
        for line in (target / "pyproject.toml").read_text().splitlines():
            if "mcp" in line or "fastapi" in line or "uvicorn" in line:
                print(f"  {line.strip()}")


if __name__ == "__main__":
    main()
