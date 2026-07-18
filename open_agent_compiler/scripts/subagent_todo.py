"""Subagent Todo Manager — file-based todo list for subagents.

Subagents in OpenCode cannot use the host's todowrite/todoread tools,
so this script gives them an equivalent JSON-file backend. The workflow
prompt's STEP 0 block invokes this CLI; see workflow_prompt/todo_block.

Storage location precedence:
  1. $OAC_TODOS_DIR (intended for tests)
  2. $XDG_DATA_HOME/oac/agent_todos (production isolation)
  3. <repo-root>/.agent_todos (v1 fallback; works when scripts/ is at the
     top level of a compiled tree)

Files are named: todo_<safe_agent_name>_<run_id>.json. Each run gets a
unique id so concurrent runs of the same agent don't trample each other.
Old lists (>1 day by mtime) are pruned automatically on every init.

Usage:
    uv run scripts/subagent_todo.py init <agent_name> [--run-id <id>]
    uv run scripts/subagent_todo.py add <agent_name> --run-id <id> \\
        --subject '...' [--description '...'] [--active-form '...']
    uv run scripts/subagent_todo.py list <agent_name> --run-id <id> [--json]
    uv run scripts/subagent_todo.py get <agent_name> <task_id> --run-id <id>
    uv run scripts/subagent_todo.py update <agent_name> <task_id> --run-id <id> \\
        [--status pending|in_progress|completed] [--subject '...']
    uv run scripts/subagent_todo.py delete <agent_name> <task_id> --run-id <id>
    uv run scripts/subagent_todo.py clear <agent_name> --run-id <id>
    uv run scripts/subagent_todo.py cleanup

agent_name and task_id may be passed positionally or as --agent-name /
--task-id / --id keyword arguments — LLMs use both forms.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

VALID_STATUSES = ["pending", "in_progress", "completed"]


def _todos_dir() -> Path:
    override = os.environ.get("OAC_TODOS_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "oac" / "agent_todos"
    # v1 fallback: <repo-root>/.agent_todos when scripts/ sits at the top
    # level of a compiled tree (scripts/subagent_todo.py -> repo root).
    return Path(__file__).resolve().parent.parent / ".agent_todos"


def ensure_dir() -> None:
    _todos_dir().mkdir(parents=True, exist_ok=True)


def generate_run_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


def default_run_id() -> str:
    return datetime.now().strftime("%Y%m%d")


def get_todo_file_path(agent_name: str, run_id: str) -> Path:
    safe = agent_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return _todos_dir() / f"todo_{safe}_{run_id}.json"


def generate_task_id() -> str:
    return uuid.uuid4().hex[:8]


def load_todo_list(agent_name: str, run_id: str) -> dict:
    path = get_todo_file_path(agent_name, run_id)
    if not path.exists():
        return {
            "agent_name": agent_name,
            "run_id": run_id,
            "created_at": datetime.now().isoformat(),
            "tasks": [],
        }
    return json.loads(path.read_text())


def save_todo_list(agent_name: str, run_id: str, data: dict) -> None:
    ensure_dir()
    data["updated_at"] = datetime.now().isoformat()
    get_todo_file_path(agent_name, run_id).write_text(json.dumps(data, indent=2))


def init_todo_list(agent_name: str, run_id: str | None = None) -> dict:
    cleanup_old_lists()
    if run_id is None:
        run_id = default_run_id()
    path = get_todo_file_path(agent_name, run_id)
    now = datetime.now().isoformat()
    data = {
        "agent_name": agent_name,
        "run_id": run_id,
        "created_at": now,
        "updated_at": now,
        "tasks": [],
    }
    save_todo_list(agent_name, run_id, data)
    return {
        "success": True, "agent_name": agent_name, "run_id": run_id,
        "path": str(path),
        "message": f"Todo list initialized for {agent_name} (run: {run_id})",
    }


def add_task(
    agent_name: str, run_id: str, subject: str,
    description: str = "", active_form: str | None = None,
    status: str = "pending",
) -> dict:
    if status not in VALID_STATUSES:
        status = "pending"
    data = load_todo_list(agent_name, run_id)
    task = {
        "id": generate_task_id(),
        "subject": subject,
        "description": description,
        "active_form": active_form or f"Working on: {subject}",
        "status": status,
        "created_at": datetime.now().isoformat(),
    }
    data["tasks"].append(task)
    save_todo_list(agent_name, run_id, data)
    return {"success": True, "task": task}


def list_tasks(agent_name: str, run_id: str) -> dict:
    data = load_todo_list(agent_name, run_id)
    return {
        "success": True, "agent_name": agent_name, "run_id": run_id,
        "task_count": len(data["tasks"]), "tasks": data["tasks"],
    }


def get_task(agent_name: str, run_id: str, task_id: str) -> dict:
    data = load_todo_list(agent_name, run_id)
    for task in data["tasks"]:
        if task["id"] == task_id:
            return {"success": True, "task": task}
    return {"success": False, "error": f"Task {task_id} not found"}


def update_task(
    agent_name: str, run_id: str, task_id: str,
    subject: str | None = None, description: str | None = None,
    active_form: str | None = None, status: str | None = None,
) -> dict:
    data = load_todo_list(agent_name, run_id)
    for task in data["tasks"]:
        if task["id"] == task_id:
            if subject is not None:
                task["subject"] = subject
            if description is not None:
                task["description"] = description
            if active_form is not None:
                task["active_form"] = active_form
            if status is not None and status in VALID_STATUSES:
                task["status"] = status
            task["updated_at"] = datetime.now().isoformat()
            save_todo_list(agent_name, run_id, data)
            return {"success": True, "task": task}
    return {"success": False, "error": f"Task {task_id} not found"}


def delete_task(agent_name: str, run_id: str, task_id: str) -> dict:
    data = load_todo_list(agent_name, run_id)
    before = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
    if len(data["tasks"]) == before:
        return {"success": False, "error": f"Task {task_id} not found"}
    save_todo_list(agent_name, run_id, data)
    return {"success": True, "deleted": task_id}


def clear_todo_list(agent_name: str, run_id: str) -> dict:
    path = get_todo_file_path(agent_name, run_id)
    if path.exists():
        path.unlink()
        return {"success": True, "message": f"Todo list cleared for {agent_name} (run: {run_id})"}
    return {"success": True, "message": f"No todo list found for {agent_name} (run: {run_id})"}


def cleanup_old_lists() -> dict:
    ensure_dir()
    cutoff = datetime.now() - timedelta(days=1)
    cleaned: list[str] = []
    kept: list[str] = []
    for path in _todos_dir().glob("todo_*.json"):
        if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
            path.unlink()
            cleaned.append(path.name)
        else:
            kept.append(path.name)
    return {"success": True, "cleaned": len(cleaned), "kept": len(kept), "cleaned_files": cleaned}


def _print(result: dict) -> None:
    print(json.dumps(result, indent=2))


def _format_tasks(tasks: list[dict]) -> str:
    if not tasks:
        return "No tasks found."
    icons = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    out: list[str] = []
    for t in tasks:
        out.append(f"{icons.get(t.get('status', 'pending'), '[ ]')} {t.get('subject', 'Untitled')}")
        out.append(f"    ID: {t.get('id', '')} | Status: {t.get('status', 'pending')}")
        if t.get("description"):
            out.append(f"    Description: {t['description']}")
        out.append("")
    return "\n".join(out)


def _parse_argv(argv: list[str]) -> tuple[dict, list[str]]:
    kwargs: dict = {}
    positional: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i].startswith("--"):
            key = argv[i][2:].replace("-", "_")
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                kwargs[key] = argv[i + 1]
                i += 2
            else:
                kwargs[key] = True
                i += 1
        else:
            positional.append(argv[i])
            i += 1
    return kwargs, positional


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    command, rest = args[0], args[1:]
    kwargs, positional = _parse_argv(rest)
    run_id = kwargs.get("run_id")
    agent_name = positional[0] if positional else kwargs.get("agent_name")
    task_id = (
        positional[1] if len(positional) >= 2
        else kwargs.get("task_id") or kwargs.get("id")
    )

    try:
        if command == "init":
            if not agent_name:
                print("Error: agent_name required"); return 1
            _print(init_todo_list(agent_name, run_id=run_id))
        elif command == "add":
            if not agent_name:
                print("Error: agent_name required"); return 1
            if "subject" not in kwargs:
                print("Error: --subject required"); return 1
            _print(add_task(
                agent_name=agent_name,
                run_id=run_id or default_run_id(),
                subject=kwargs["subject"],
                description=kwargs.get("description", ""),
                active_form=kwargs.get("active_form"),
                status=kwargs.get("status", "pending"),
            ))
        elif command == "list":
            if not agent_name:
                print("Error: agent_name required"); return 1
            result = list_tasks(agent_name, run_id or default_run_id())
            if "json" in kwargs:
                _print(result)
            else:
                print(f"Agent: {result['agent_name']} (run: {result['run_id']})")
                print(f"Total tasks: {result['task_count']}")
                print("-" * 40)
                print(_format_tasks(result["tasks"]))
        elif command == "get":
            if not agent_name or not task_id:
                print("Error: agent_name and task_id required"); return 1
            _print(get_task(agent_name, run_id or default_run_id(), task_id))
        elif command == "update":
            if not agent_name or not task_id:
                print("Error: agent_name and task_id required"); return 1
            _print(update_task(
                agent_name=agent_name,
                run_id=run_id or default_run_id(),
                task_id=task_id,
                subject=kwargs.get("subject"),
                description=kwargs.get("description"),
                active_form=kwargs.get("active_form"),
                status=kwargs.get("status"),
            ))
        elif command == "delete":
            if not agent_name or not task_id:
                print("Error: agent_name and task_id required"); return 1
            _print(delete_task(agent_name, run_id or default_run_id(), task_id))
        elif command == "clear":
            if not agent_name:
                print("Error: agent_name required"); return 1
            _print(clear_todo_list(agent_name, run_id or default_run_id()))
        elif command == "cleanup":
            _print(cleanup_old_lists())
        else:
            print(f"Unknown command: {command}")
            print(__doc__)
            return 1
    except Exception as exc:  # noqa: BLE001 - CLI surface
        print(json.dumps({"success": False, "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
