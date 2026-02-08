"""
Subagent Todo Manager

File-based todo list system for subagents. Each agent gets its own todo list
for the duration of a session, stored as a JSON file.

Files are named: todo_{agent_name}_{run_id}.json
Each run gets a unique ID to allow concurrent executions.
Old todo lists (older than 1 day) are automatically cleaned up.

Usage:
    uv run scripts/subagent_todo.py init <agent_name> [--run-id <id>]
    uv run scripts/subagent_todo.py add <agent_name> --run-id <id> --subject '...' --description '...' [--active-form '...']
    uv run scripts/subagent_todo.py list <agent_name> --run-id <id>
    uv run scripts/subagent_todo.py get <agent_name> <task_id> --run-id <id>
    uv run scripts/subagent_todo.py update <agent_name> <task_id> --run-id <id> [--status pending|in_progress|completed] [--subject '...']
    uv run scripts/subagent_todo.py delete <agent_name> <task_id> --run-id <id>
    uv run scripts/subagent_todo.py clear <agent_name> --run-id <id>
    uv run scripts/subagent_todo.py cleanup

    agent_name and task_id can also be passed as keyword args:
    uv run scripts/subagent_todo.py update --agent-name <name> --task-id <id> --run-id <id> --status '...'
"""

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Storage directory
TODOS_DIR = Path(__file__).parent.parent / ".agent_todos"

VALID_STATUSES = ["pending", "in_progress", "completed"]


def ensure_dir():
    """Ensure todos directory exists."""
    TODOS_DIR.mkdir(parents=True, exist_ok=True)


def generate_run_id() -> str:
    """Generate a unique run ID (timestamp + random)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = uuid.uuid4().hex[:6]
    return f"{ts}_{rand}"


def default_run_id() -> str:
    """Fallback run ID using date (backward-compatible with old naming)."""
    return datetime.now().strftime("%Y%m%d")


def get_todo_file_path(agent_name: str, run_id: str) -> Path:
    """Get path for an agent's todo file."""
    # Sanitize agent name for filename
    safe_name = agent_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return TODOS_DIR / f"todo_{safe_name}_{run_id}.json"


def generate_task_id() -> str:
    """Generate a unique task ID."""
    return str(uuid.uuid4().hex[:8])


def load_todo_list(agent_name: str, run_id: str) -> dict:
    """Load an agent's todo list from file."""
    path = get_todo_file_path(agent_name, run_id)
    if not path.exists():
        return {
            "agent_name": agent_name,
            "run_id": run_id,
            "created_at": datetime.now().isoformat(),
            "tasks": [],
        }

    with open(path) as f:
        return json.load(f)


def save_todo_list(agent_name: str, run_id: str, data: dict):
    """Save an agent's todo list to file."""
    ensure_dir()
    path = get_todo_file_path(agent_name, run_id)
    data["updated_at"] = datetime.now().isoformat()

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def init_todo_list(agent_name: str, run_id: str | None = None) -> dict:
    """Initialize a new todo list for an agent.

    If run_id is provided, uses it (supports concurrent runs).
    If not provided, falls back to date-based ID (backward compatible).
    """
    # First, run cleanup to remove old lists
    cleanup_old_lists()

    if run_id is None:
        run_id = default_run_id()

    path = get_todo_file_path(agent_name, run_id)

    data = {
        "agent_name": agent_name,
        "run_id": run_id,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "tasks": [],
    }

    save_todo_list(agent_name, run_id, data)

    return {
        "success": True,
        "agent_name": agent_name,
        "run_id": run_id,
        "path": str(path),
        "message": f"Todo list initialized for {agent_name} (run: {run_id})",
    }


def add_task(
    agent_name: str,
    run_id: str,
    subject: str,
    description: str = "",
    active_form: str | None = None,
    status: str = "pending",
) -> dict:
    """Add a new task to an agent's todo list."""
    if status not in VALID_STATUSES:
        status = "pending"

    data = load_todo_list(agent_name, run_id)

    task_id = generate_task_id()
    task = {
        "id": task_id,
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
    """List all tasks in an agent's todo list."""
    data = load_todo_list(agent_name, run_id)

    return {
        "success": True,
        "agent_name": agent_name,
        "run_id": run_id,
        "task_count": len(data["tasks"]),
        "tasks": data["tasks"],
    }


def get_task(agent_name: str, run_id: str, task_id: str) -> dict:
    """Get a specific task by ID."""
    data = load_todo_list(agent_name, run_id)

    for task in data["tasks"]:
        if task["id"] == task_id:
            return {"success": True, "task": task}

    return {"success": False, "error": f"Task {task_id} not found"}


def update_task(
    agent_name: str,
    run_id: str,
    task_id: str,
    subject: str | None = None,
    description: str | None = None,
    active_form: str | None = None,
    status: str | None = None,
) -> dict:
    """Update a task's fields."""
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
    """Delete a task from an agent's todo list."""
    data = load_todo_list(agent_name, run_id)

    original_count = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]

    if len(data["tasks"]) == original_count:
        return {"success": False, "error": f"Task {task_id} not found"}

    save_todo_list(agent_name, run_id, data)

    return {"success": True, "deleted": task_id}


def clear_todo_list(agent_name: str, run_id: str) -> dict:
    """Remove an agent's entire todo list file."""
    path = get_todo_file_path(agent_name, run_id)

    if path.exists():
        path.unlink()
        return {
            "success": True,
            "message": f"Todo list cleared for {agent_name} (run: {run_id})",
        }

    return {
        "success": True,
        "message": f"No todo list found for {agent_name} (run: {run_id})",
    }


def cleanup_old_lists() -> dict:
    """Clean up old todo lists (older than 1 day)."""
    ensure_dir()

    cutoff = datetime.now() - timedelta(days=1)

    cleaned = []
    kept = []

    for path in TODOS_DIR.glob("todo_*.json"):
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime < cutoff:
            path.unlink()
            cleaned.append(path.name)
        else:
            kept.append(path.name)

    return {
        "success": True,
        "cleaned": len(cleaned),
        "kept": len(kept),
        "cleaned_files": cleaned,
    }


def print_result(result: dict):
    """Print result as JSON."""
    print(json.dumps(result, indent=2))


def format_tasks_for_display(tasks: list[dict]) -> str:
    """Format tasks as a readable string."""
    if not tasks:
        return "No tasks found."

    lines = []
    status_icons = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}

    for task in tasks:
        icon = status_icons.get(task.get("status", "pending"), "[ ]")
        subject = task.get("subject", "Untitled")
        task_id = task.get("id", "")
        status = task.get("status", "pending")

        lines.append(f"{icon} {subject}")
        lines.append(f"    ID: {task_id} | Status: {status}")

        if task.get("description"):
            lines.append(f"    Description: {task['description']}")

        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    # Parse keyword arguments
    kwargs = {}
    positional = []
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:].replace("-", "_")
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                kwargs[key] = args[i + 1]
                i += 2
            else:
                kwargs[key] = True
                i += 1
        else:
            positional.append(args[i])
            i += 1

    run_id = kwargs.get("run_id")

    # Allow agent_name and task_id as either positional or keyword args.
    # LLMs often use --agent-name/--task-id/--id instead of positional args.
    agent_name = positional[0] if len(positional) >= 1 else kwargs.get("agent_name")
    task_id = (
        positional[1]
        if len(positional) >= 2
        else (kwargs.get("task_id") or kwargs.get("id"))
    )

    try:
        if command == "init":
            if not agent_name:
                print("Error: agent_name required")
                sys.exit(1)

            result = init_todo_list(agent_name, run_id=run_id)
            print_result(result)

        elif command == "add":
            if not agent_name:
                print("Error: agent_name required")
                sys.exit(1)
            if "subject" not in kwargs:
                print("Error: --subject required")
                sys.exit(1)

            effective_run_id = run_id or default_run_id()
            result = add_task(
                agent_name=agent_name,
                run_id=effective_run_id,
                subject=kwargs["subject"],
                description=kwargs.get("description", ""),
                active_form=kwargs.get("active_form"),
                status=kwargs.get("status", "pending"),
            )
            print_result(result)

        elif command == "list":
            if not agent_name:
                print("Error: agent_name required")
                sys.exit(1)

            effective_run_id = run_id or default_run_id()
            result = list_tasks(agent_name, effective_run_id)

            if "json" in kwargs:
                print_result(result)
            else:
                print(f"Agent: {result['agent_name']} (run: {result['run_id']})")
                print(f"Total tasks: {result['task_count']}")
                print("-" * 40)
                print(format_tasks_for_display(result["tasks"]))

        elif command == "get":
            if not agent_name or not task_id:
                print("Error: agent_name and task_id required")
                sys.exit(1)

            effective_run_id = run_id or default_run_id()
            result = get_task(agent_name, effective_run_id, task_id)
            print_result(result)

        elif command == "update":
            if not agent_name or not task_id:
                print("Error: agent_name and task_id required")
                sys.exit(1)

            effective_run_id = run_id or default_run_id()
            result = update_task(
                agent_name=agent_name,
                run_id=effective_run_id,
                task_id=task_id,
                subject=kwargs.get("subject"),
                description=kwargs.get("description"),
                active_form=kwargs.get("active_form"),
                status=kwargs.get("status"),
            )
            print_result(result)

        elif command == "delete":
            if not agent_name or not task_id:
                print("Error: agent_name and task_id required")
                sys.exit(1)

            effective_run_id = run_id or default_run_id()
            result = delete_task(agent_name, effective_run_id, task_id)
            print_result(result)

        elif command == "clear":
            if not agent_name:
                print("Error: agent_name required")
                sys.exit(1)

            effective_run_id = run_id or default_run_id()
            result = clear_todo_list(agent_name, effective_run_id)
            print_result(result)

        elif command == "cleanup":
            result = cleanup_old_lists()
            print_result(result)

        else:
            print(f"Unknown command: {command}")
            print(__doc__)
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)
