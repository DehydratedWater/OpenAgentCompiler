#!/usr/bin/env python3
"""OpenCode Manager — wrapper around the `opencode` CLI / web server.

Bundled script used when an agent's compiled tree references it via
subagents in 'primary' mode (the SECURITY POLICY block emits
`uv run scripts/opencode_manager.py run --agent <name> "..."`).

Subcommands:
  server start|stop|status|restart  — manage a persistent web server
  run --agent <name> "<prompt>"     — dispatch an agent (attaches to
                                       the running server when present)
  logs [--limit N]                  — list recent run logs

Ported from v1 with two dependency swaps:
- httpx → urllib.request (no new runtime dep).
- python-dotenv → optional, lazy import; missing dotenv is non-fatal.

Locations:
  PROJECT_ROOT = parent of this file's parent (matches v1 layout where
                 the bundled script lives one level below the project
                 root inside scripts/).
  XDG_DATA_HOME (when set) is used as the session storage root so the
                 web UI sees the same sessions the run subcommand starts.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Optional .env loader — present in many user projects, but not required.
with contextlib.suppress(ImportError):
    from dotenv import load_dotenv  # type: ignore[import-not-found]

    load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "run_logs"
PID_FILE = PROJECT_ROOT / ".opencode_server.pid"
OPENCODE_PORT = int(os.environ.get("OAC_OPENCODE_PORT", "4096"))
OPENCODE_URL = f"http://localhost:{OPENCODE_PORT}"


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def _opencode_data_home() -> str:
    """Match the web server's storage so 'run' sessions show up in the UI."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return xdg
    return str(PROJECT_ROOT / ".opencode" / "data")


class OpenCodeManager:
    """Server lifecycle + agent dispatch."""

    @staticmethod
    def is_server_running() -> bool:
        if not PID_FILE.exists():
            return False
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink(missing_ok=True)
            return False
        return _http_ok(f"{OPENCODE_URL}/api/health")

    @staticmethod
    def start_server() -> bool:
        if OpenCodeManager.is_server_running():
            print(f"[INFO] OpenCode server already running on port {OPENCODE_PORT}")
            return True
        print(f"[INFO] Starting OpenCode web server on port {OPENCODE_PORT}…")
        env = os.environ.copy()
        env["XDG_DATA_HOME"] = _opencode_data_home()
        try:
            process = subprocess.Popen(
                ["opencode", "web", "--hostname", "0.0.0.0",
                 "--port", str(OPENCODE_PORT)],
                cwd=PROJECT_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        except FileNotFoundError:
            print("[ERROR] 'opencode' command not found in PATH.")
            return False
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] Failed to start server: {exc}")
            return False
        PID_FILE.write_text(str(process.pid))
        for _ in range(30):
            time.sleep(1)
            if OpenCodeManager.is_server_running():
                print(f"[INFO] OpenCode server started (PID: {process.pid})")
                print(f"[INFO] Web UI: {OPENCODE_URL}")
                return True
        print("[ERROR] Server started but not responding")
        return False

    @staticmethod
    def stop_server() -> bool:
        if not PID_FILE.exists():
            print("[INFO] No PID file found, server not running")
            return True
        try:
            pid = int(PID_FILE.read_text().strip())
        except ValueError:
            print("[ERROR] Invalid PID in file")
            PID_FILE.unlink(missing_ok=True)
            return False
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"[INFO] Sent SIGTERM to process {pid}")
        except ProcessLookupError:
            print("[INFO] Process already stopped")
            PID_FILE.unlink(missing_ok=True)
            return True
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                print("[INFO] OpenCode server stopped")
                PID_FILE.unlink(missing_ok=True)
                return True
        print("[WARN] Process didn't exit gracefully, sending SIGKILL")
        os.kill(pid, signal.SIGKILL)
        PID_FILE.unlink(missing_ok=True)
        return True

    @staticmethod
    def get_status() -> dict:
        running = OpenCodeManager.is_server_running()
        pid: int | None = None
        if PID_FILE.exists():
            with contextlib.suppress(ValueError):
                pid = int(PID_FILE.read_text().strip())
        return {
            "running": running,
            "port": OPENCODE_PORT,
            "url": OPENCODE_URL if running else None,
            "pid": pid if running else None,
            "pid_file": str(PID_FILE),
        }

    @staticmethod
    def _agent_is_subagent(agent: str) -> bool:
        md = PROJECT_ROOT / ".opencode" / "agents" / f"{agent}.md"
        if not md.exists():
            return False
        for line in md.read_text().splitlines():
            stripped = line.strip()
            if stripped == "---":
                continue
            if stripped.startswith("mode:"):
                return stripped.split(":", 1)[1].strip() == "subagent"
            if not stripped or stripped == "---":
                break
        return False

    @staticmethod
    async def run_agent(
        agent: str, prompt: str, log_prefix: str = "opencode",
        ensure_server: bool = True,
    ) -> dict:
        start = datetime.now()

        if OpenCodeManager._agent_is_subagent(agent):
            print(
                f"[WARN] '{agent}' is a subagent — prefer the Task tool"
                " (subagent_type) over opencode_manager.py."
            )

        if ensure_server and not OpenCodeManager.is_server_running():
            print("[INFO] Starting web server for monitoring UI…")
            OpenCodeManager.start_server()
        server_running = OpenCodeManager.is_server_running()

        print(f"[{start.strftime('%H:%M:%S')}] Running agent: {agent}")
        print(f"[INFO] Prompt: {prompt[:100]}{'…' if len(prompt) > 100 else ''}")
        if server_running:
            print(f"[INFO] Web UI: {OPENCODE_URL}")

        cmd = ["opencode", "run", "--log-level", "DEBUG", "--agent", agent]
        if server_running:
            cmd.extend(["--attach", OPENCODE_URL])
        cmd.append(prompt)

        env = os.environ.copy()
        env["XDG_DATA_HOME"] = _opencode_data_home()

        stdout = b""
        stderr = b""
        rc = -1
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=PROJECT_ROOT, env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            rc = proc.returncode or 0
        except FileNotFoundError:
            print("[ERROR] 'opencode' command not found")
            stderr = b"FileNotFoundError: 'opencode' command not found"
            rc = 127
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] Failed to run agent: {exc}")
            stderr = f"Exception: {exc}".encode()
            rc = 1
        end = datetime.now()

        log_path = OpenCodeManager._save_log(
            prefix=log_prefix, agent=agent, prompt=prompt,
            stdout=stdout, stderr=stderr, return_code=rc,
            start_time=start, end_time=end,
        )
        return {
            "success": rc == 0,
            "return_code": rc,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "log_path": str(log_path) if log_path else None,
            "duration": (end - start).total_seconds(),
        }

    @staticmethod
    def _save_log(
        prefix: str, agent: str, prompt: str,
        stdout: bytes, stderr: bytes, return_code: int,
        start_time: datetime, end_time: datetime,
    ) -> Path | None:
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            ts = start_time.strftime("%Y-%m-%d_%H-%M-%S")
            path = LOGS_DIR / f"{prefix}_{ts}.log"
            dur = (end_time - start_time).total_seconds()
            body = (
                "=" * 80 + "\n"
                "OPENCODE RUN LOG\n" + "=" * 80 + "\n"
                f"Prefix: {prefix}\nAgent: {agent}\n"
                f"Timestamp: {start_time:%Y-%m-%d %H:%M:%S}\n"
                f"Duration: {dur:.1f}s\nReturn Code: {return_code}\n"
                f"Server: {OPENCODE_URL}\n"
                + "-" * 80 + "\nPROMPT:\n" + "-" * 80 + f"\n{prompt}\n"
                + "-" * 80 + "\nSTDOUT:\n" + "-" * 80 + "\n"
                + (stdout.decode("utf-8", errors="replace") if stdout else "(empty)") + "\n"
                + "-" * 80 + "\nSTDERR:\n" + "-" * 80 + "\n"
                + (stderr.decode("utf-8", errors="replace") if stderr else "(empty)") + "\n"
                + "=" * 80 + "\nEND OF LOG\n" + "=" * 80 + "\n"
            )
            path.write_text(body)
            print(f"[INFO] Run log saved: {path}")
            return path
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Failed to save log: {exc}")
            return None

    @staticmethod
    def get_recent_logs(limit: int = 20) -> list[dict]:
        if not LOGS_DIR.exists():
            return []
        files = sorted(
            LOGS_DIR.glob("*.log"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        return [
            {
                "filename": p.name,
                "path": str(p),
                "size": p.stat().st_size,
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            }
            for p in files[:limit]
        ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenCode Manager — wrapper around the opencode CLI."
    )
    subs = parser.add_subparsers(dest="command")

    server = subs.add_parser("server", help="Manage opencode web server")
    server.add_argument(
        "action", choices=["start", "stop", "status", "restart"],
    )

    run = subs.add_parser("run", help="Run an agent via the server")
    run.add_argument("--agent", "-a", required=True)
    run.add_argument("--prefix", "-p", default="opencode")
    run.add_argument("--no-server", action="store_true")
    run.add_argument("--output", "-o", action="store_true")
    run.add_argument("--output-only", action="store_true")
    run.add_argument("prompt", nargs="*")

    logs = subs.add_parser("logs", help="List recent log files")
    logs.add_argument("--limit", "-l", type=int, default=20)
    return parser


def cmd_server(args: argparse.Namespace) -> int:
    if args.action == "start":
        return 0 if OpenCodeManager.start_server() else 1
    if args.action == "stop":
        return 0 if OpenCodeManager.stop_server() else 1
    if args.action == "status":
        status = OpenCodeManager.get_status()
        if status["running"]:
            print("OpenCode server: RUNNING")
            print(f"  URL: {status['url']}")
            print(f"  PID: {status['pid']}")
            print(f"  Port: {status['port']}")
        else:
            print("OpenCode server: STOPPED")
            print(f"  Port: {status['port']}")
        return 0
    if args.action == "restart":
        OpenCodeManager.stop_server()
        time.sleep(1)
        return 0 if OpenCodeManager.start_server() else 1
    return 1


def cmd_run(args: argparse.Namespace) -> int:
    if not args.prompt:
        print("Error: prompt is required")
        return 1
    prompt = " ".join(args.prompt)
    result = asyncio.run(
        OpenCodeManager.run_agent(
            agent=args.agent,
            prompt=prompt,
            log_prefix=args.prefix or "opencode",
            ensure_server=not args.no_server,
        )
    )
    if result["success"]:
        print("\n[SUCCESS] Agent completed")
    else:
        print(f"\n[FAILED] Agent returned code {result['return_code']}")
    if args.output:
        print("\n" + "=" * 60)
        print("AGENT OUTPUT:")
        print("=" * 60)
        print(result.get("stdout") or "(no output)")
        print("=" * 60)
    if args.output_only and result.get("stdout"):
        print(result["stdout"], end="")
    return result["return_code"]


def cmd_logs(args: argparse.Namespace) -> int:
    logs = OpenCodeManager.get_recent_logs(limit=args.limit)
    if not logs:
        print("No logs found")
        return 0
    print(f"Recent logs ({len(logs)}):")
    print("-" * 60)
    for log in logs:
        print(f"  {log['filename']} ({log['size']} bytes, {log['modified']})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "server":
        return cmd_server(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "logs":
        return cmd_logs(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
