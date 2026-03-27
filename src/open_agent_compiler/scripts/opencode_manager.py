#!/usr/bin/env python3
"""
OpenCode Manager - Central wrapper for opencode web server.

Manages a persistent opencode web server and provides unified agent execution.

Usage:
    # Server management
    uv run scripts/opencode_manager.py server start
    uv run scripts/opencode_manager.py server stop
    uv run scripts/opencode_manager.py server status

    # Run agent via server
    uv run scripts/opencode_manager.py run --agent <agent> "prompt"
"""

import argparse
import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Directories and configuration
PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "run_logs"
PID_FILE = PROJECT_ROOT / ".opencode_server.pid"
OPENCODE_PORT = 4096
OPENCODE_URL = f"http://localhost:{OPENCODE_PORT}"


class OpenCodeManager:
    """Central manager for OpenCode web server and agent execution."""

    @staticmethod
    def is_server_running() -> bool:
        """
        Check if the opencode web server is running.

        Returns:
            True if server is running and responsive, False otherwise
        """
        # Check PID file
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                # Check if process exists
                os.kill(pid, 0)
            except (ValueError, ProcessLookupError, PermissionError):
                # Process doesn't exist or invalid PID
                PID_FILE.unlink(missing_ok=True)
                return False
        else:
            return False

        # Verify server is actually responding
        try:
            response = httpx.get(f"{OPENCODE_URL}/api/health", timeout=2.0)
            return response.status_code == 200
        except Exception:
            return False

    @staticmethod
    def start_server() -> bool:
        """
        Start the opencode web server.

        Returns:
            True if server started successfully, False otherwise
        """
        if OpenCodeManager.is_server_running():
            print(f"[INFO] OpenCode server already running on port {OPENCODE_PORT}")
            return True

        print(f"[INFO] Starting OpenCode web server on port {OPENCODE_PORT}...")

        try:
            # Start opencode web server in background
            # Use --hostname 0.0.0.0 to make it accessible across VPN
            # Set XDG_DATA_HOME to match agent execution so sessions appear in web UI
            env = os.environ.copy()
            env["XDG_DATA_HOME"] = str(PROJECT_ROOT / ".opencode" / "data")

            process = subprocess.Popen(
                [
                    "opencode",
                    "web",
                    "--hostname",
                    "0.0.0.0",
                    "--port",
                    str(OPENCODE_PORT),
                ],
                cwd=PROJECT_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )

            # Save PID
            PID_FILE.write_text(str(process.pid))

            # Wait for server to be ready
            for _ in range(30):  # Wait up to 30 seconds
                time.sleep(1)
                if OpenCodeManager.is_server_running():
                    print(f"[INFO] OpenCode server started (PID: {process.pid})")
                    print(f"[INFO] Web UI: {OPENCODE_URL}")
                    return True

            print("[ERROR] Server started but not responding")
            return False

        except FileNotFoundError:
            print(
                "[ERROR] 'opencode' command not found. Make sure it's installed and in PATH."
            )
            return False
        except Exception as e:
            print(f"[ERROR] Failed to start server: {e}")
            return False

    @staticmethod
    def stop_server() -> bool:
        """
        Stop the opencode web server.

        Returns:
            True if server stopped successfully, False otherwise
        """
        if not PID_FILE.exists():
            print("[INFO] No PID file found, server not running")
            return True

        try:
            pid = int(PID_FILE.read_text().strip())

            # Try graceful shutdown first
            os.kill(pid, signal.SIGTERM)
            print(f"[INFO] Sent SIGTERM to process {pid}")

            # Wait for process to exit
            for _ in range(10):
                time.sleep(0.5)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    print("[INFO] OpenCode server stopped")
                    PID_FILE.unlink(missing_ok=True)
                    return True

            # Force kill if still running
            print("[WARN] Process didn't exit gracefully, sending SIGKILL")
            os.kill(pid, signal.SIGKILL)
            PID_FILE.unlink(missing_ok=True)
            return True

        except ProcessLookupError:
            print("[INFO] Process already stopped")
            PID_FILE.unlink(missing_ok=True)
            return True
        except ValueError:
            print("[ERROR] Invalid PID in file")
            PID_FILE.unlink(missing_ok=True)
            return False
        except Exception as e:
            print(f"[ERROR] Failed to stop server: {e}")
            return False

    @staticmethod
    def get_status() -> dict:
        """
        Get detailed server status.

        Returns:
            Dict with status information
        """
        running = OpenCodeManager.is_server_running()
        pid = None

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
    async def run_agent(
        agent: str,
        prompt: str,
        log_prefix: str = "opencode",
        ensure_server: bool = True,
    ) -> dict:
        """
        Run an agent. The web server (if running) provides a UI for monitoring.

        Args:
            agent: Agent path (e.g., "goals/my-orchestrator")
            prompt: The prompt to send to the agent
            log_prefix: Prefix for log file names
            ensure_server: If True, start server if not running (for web UI access)

        Returns:
            Dict with run results including return_code, stdout, stderr, log_path
        """
        start_time = datetime.now()

        # Guard: refuse to run subagents directly
        agent_md = PROJECT_ROOT / ".opencode" / "agents" / f"{agent}.md"
        if agent_md.exists():
            with open(agent_md) as f:
                for line in f:
                    line = line.strip()
                    if line == "---":
                        continue
                    if line.startswith("mode:"):
                        mode = line.split(":", 1)[1].strip()
                        if mode == "subagent":
                            print(
                                f"[WARN] '{agent}' is a subagent — it should be invoked via the Task tool, not opencode_manager.py."
                            )
                            print(
                                f'[WARN] Proceeding anyway, but prefer: Task tool → "{agent}"'
                            )
                            break
                        break
                    if not line or line == "---":
                        break

        # Ensure web server is running for monitoring
        if ensure_server and not OpenCodeManager.is_server_running():
            print("[INFO] Starting web server for monitoring UI...")
            OpenCodeManager.start_server()

        server_running = OpenCodeManager.is_server_running()

        print(f"[{start_time.strftime('%H:%M:%S')}] Running agent: {agent}")
        print(f"[INFO] Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
        if server_running:
            print(f"[INFO] Web UI: {OPENCODE_URL}")

        # Build command — attach to running server so session is visible in web UI
        cmd = [
            "opencode",
            "run",
            "--log-level",
            "DEBUG",
            "--agent",
            agent,
        ]
        if server_running:
            cmd.extend(["--attach", OPENCODE_URL])
        cmd.append(prompt)
        print(f"[DEBUG] Full command: {' '.join(cmd[:5])} ...")
        print(f"[DEBUG] Working dir: {PROJECT_ROOT}")

        stdout = b""
        stderr = b""
        return_code = -1

        # Set XDG_DATA_HOME to match the opencode web server's storage location
        # This ensures sessions appear in the web UI
        env = os.environ.copy()
        env["XDG_DATA_HOME"] = str(PROJECT_ROOT / ".opencode" / "data")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=PROJECT_ROOT,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()
            return_code = process.returncode or 0

            if return_code != 0:
                print(f"[ERROR] Agent returned non-zero exit code: {return_code}")
                if stderr:
                    print(f"[ERROR] stderr: {stderr.decode()[:500]}")
            else:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Agent completed successfully"
                )

        except FileNotFoundError:
            print("[ERROR] 'opencode' command not found")
            stderr = b"FileNotFoundError: 'opencode' command not found"
            return_code = 127
        except Exception as e:
            print(f"[ERROR] Failed to run agent: {e}")
            stderr = f"Exception: {e}".encode()
            return_code = 1

        end_time = datetime.now()

        # Save log
        log_path = OpenCodeManager._save_log(
            prefix=log_prefix,
            agent=agent,
            prompt=prompt,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
            start_time=start_time,
            end_time=end_time,
        )

        return {
            "success": return_code == 0,
            "return_code": return_code,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "log_path": str(log_path) if log_path else None,
            "duration": (end_time - start_time).total_seconds(),
        }

    @staticmethod
    def _save_log(
        prefix: str,
        agent: str,
        prompt: str,
        stdout: bytes,
        stderr: bytes,
        return_code: int,
        start_time: datetime,
        end_time: datetime,
    ) -> Path | None:
        """
        Save run output to a timestamped log file.

        Returns:
            Path to created log file, or None on error
        """
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)

            timestamp = start_time.strftime("%Y-%m-%d_%H-%M-%S")
            log_file = LOGS_DIR / f"{prefix}_{timestamp}.log"

            duration = (end_time - start_time).total_seconds()

            content = f"""================================================================================
OPENCODE RUN LOG
================================================================================
Prefix: {prefix}
Agent: {agent}
Timestamp: {start_time.strftime("%Y-%m-%d %H:%M:%S")}
Duration: {duration:.1f}s
Return Code: {return_code}
Server: {OPENCODE_URL}
--------------------------------------------------------------------------------
PROMPT:
--------------------------------------------------------------------------------
{prompt}
--------------------------------------------------------------------------------
STDOUT:
--------------------------------------------------------------------------------
{stdout.decode("utf-8", errors="replace") if stdout else "(empty)"}
--------------------------------------------------------------------------------
STDERR:
--------------------------------------------------------------------------------
{stderr.decode("utf-8", errors="replace") if stderr else "(empty)"}
================================================================================
END OF LOG
================================================================================
"""

            log_file.write_text(content)
            print(f"[INFO] Run log saved: {log_file}")
            return log_file

        except Exception as e:
            print(f"[WARN] Failed to save log: {e}")
            return None

    @staticmethod
    def get_recent_logs(limit: int = 20) -> list[dict]:
        """
        Get list of recent log files.

        Args:
            limit: Maximum number of logs to return

        Returns:
            List of log file info dicts
        """
        logs = []

        if not LOGS_DIR.exists():
            return logs

        log_files = sorted(
            LOGS_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
        )

        for log_file in log_files[:limit]:
            stat = log_file.stat()
            logs.append(
                {
                    "filename": log_file.name,
                    "path": str(log_file),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )

        return logs


def cmd_server(args: argparse.Namespace) -> int:
    """Handle server subcommand."""
    if args.action == "start":
        success = OpenCodeManager.start_server()
        return 0 if success else 1

    elif args.action == "stop":
        success = OpenCodeManager.stop_server()
        return 0 if success else 1

    elif args.action == "status":
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

    elif args.action == "restart":
        OpenCodeManager.stop_server()
        time.sleep(1)
        success = OpenCodeManager.start_server()
        return 0 if success else 1

    return 1


def cmd_run(args: argparse.Namespace) -> int:
    """Handle run subcommand."""
    if not args.agent:
        print("Error: --agent is required")
        return 1

    if not args.prompt:
        print("Error: prompt is required")
        return 1

    prompt = " ".join(args.prompt)
    prefix = args.prefix or "opencode"

    result = asyncio.run(
        OpenCodeManager.run_agent(
            agent=args.agent,
            prompt=prompt,
            log_prefix=prefix,
            ensure_server=not args.no_server,
        )
    )

    if result["success"]:
        print("\n[SUCCESS] Agent completed")
    else:
        print(f"\n[FAILED] Agent returned code {result['return_code']}")

    # Print agent output if requested
    if args.output:
        print("\n" + "=" * 60)
        print("AGENT OUTPUT:")
        print("=" * 60)
        if result.get("stdout"):
            print(result["stdout"])
        else:
            print("(no output)")
        print("=" * 60)

    # Return just the output for piping (when --output-only is used)
    if args.output_only and result.get("stdout"):
        # Print only the stdout, nothing else - suitable for capturing
        print(result["stdout"], end="")

    return result["return_code"]


def cmd_logs(args: argparse.Namespace) -> int:
    """Handle logs subcommand."""
    logs = OpenCodeManager.get_recent_logs(limit=args.limit)

    if not logs:
        print("No logs found")
        return 0

    print(f"Recent logs ({len(logs)}):")
    print("-" * 60)
    for log in logs:
        print(f"  {log['filename']} ({log['size']} bytes, {log['modified']})")

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="OpenCode Manager - Central wrapper for opencode web server"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Server subcommand
    server_parser = subparsers.add_parser("server", help="Manage opencode web server")
    server_parser.add_argument(
        "action", choices=["start", "stop", "status", "restart"], help="Server action"
    )

    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Run an agent via the server")
    run_parser.add_argument(
        "--agent",
        "-a",
        required=True,
        help="Agent path (e.g., goals/my-orchestrator)",
    )
    run_parser.add_argument(
        "--prefix", "-p", default="opencode", help="Log file prefix"
    )
    run_parser.add_argument(
        "--no-server", action="store_true", help="Don't auto-start server"
    )
    run_parser.add_argument(
        "--output",
        "-o",
        action="store_true",
        help="Print the agent's output (stdout) after completion",
    )
    run_parser.add_argument(
        "--output-only",
        action="store_true",
        help="Print ONLY the agent's stdout (for piping/capturing)",
    )
    run_parser.add_argument("prompt", nargs="*", help="Prompt to send to agent")

    # Logs subcommand
    logs_parser = subparsers.add_parser("logs", help="List recent log files")
    logs_parser.add_argument(
        "--limit", "-l", type=int, default=20, help="Maximum number of logs to show"
    )

    args = parser.parse_args()

    if args.command == "server":
        return cmd_server(args)
    elif args.command == "run":
        return cmd_run(args)
    elif args.command == "logs":
        return cmd_logs(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
