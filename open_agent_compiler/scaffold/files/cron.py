"""Cron-driver scaffolding: events.json + driver that POSTs to FastAPI.

The driver doesn't invoke agents directly anymore — it POSTs the matched
event payload to FastAPI's /events/{id}/fire route. That keeps the
agent-invocation logic in one place (app/agent_runner.py) and lets cron
stay a dumb dispatcher.
"""

from __future__ import annotations

import json

from open_agent_compiler.scaffold.config import ScaffoldConfig


_EVENTS_TEMPLATE = [
    {
        "id": "example-hourly",
        "schedule": "0 * * * *",
        "agent": "starter",
        "prompt": "Run hourly health check.",
        "context": {"trigger": "cron"},
        "enabled": False,
    },
    {
        "id": "example-daily-summary",
        "schedule": "0 9 * * *",
        "agent": "starter",
        "prompt": "Summarize yesterday's activity.",
        "context": {"trigger": "cron"},
        "enabled": False,
    },
]


def render_events_json(config: ScaffoldConfig) -> str:
    return json.dumps(_EVENTS_TEMPLATE, indent=2) + "\n"


def render_driver(config: ScaffoldConfig) -> str:
    return (
        '"""Cron driver — POSTs matched events to FastAPI.\n'
        "\n"
        "Reads CRON_EVENTS (default cron/events.json), polls every 30s,\n"
        "and for each event whose `schedule` matches the current minute\n"
        "POSTs the event payload to FASTAPI_URL/events/<id>/fire.\n"
        "\n"
        "Standardised event shape:\n"
        "    {id: str, schedule: cron-expr, agent: str, prompt: str,\n"
        "     context?: dict, enabled: bool}\n"
        "\n"
        "Minute-precision cron: 5 fields (minute hour dom month dow), each\n"
        "either '*' or comma-separated ints. Swap in croniter for ranges/steps.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "import json\n"
        "import os\n"
        "import time\n"
        "import urllib.error\n"
        "import urllib.request\n"
        "from datetime import datetime\n"
        "from pathlib import Path\n"
        "\n"
        "_EVENTS_PATH = Path(os.environ.get('CRON_EVENTS', 'cron/events.json'))\n"
        "_FASTAPI_URL = os.environ.get('FASTAPI_URL', 'http://localhost:8002')\n"
        "_POLL_S = float(os.environ.get('CRON_POLL_SECONDS', '30'))\n"
        "\n"
        "\n"
        "def _load_events() -> list[dict]:\n"
        "    if not _EVENTS_PATH.exists():\n"
        "        print(f'[cron] events file not found at {_EVENTS_PATH}')\n"
        "        return []\n"
        "    try:\n"
        "        return json.loads(_EVENTS_PATH.read_text())\n"
        "    except json.JSONDecodeError as exc:\n"
        "        print(f'[cron] {_EVENTS_PATH} is invalid JSON: {exc}')\n"
        "        return []\n"
        "\n"
        "\n"
        "def _should_fire(schedule: str, now: datetime) -> bool:\n"
        '    """Minute-precision cron check."""\n'
        "    parts = schedule.strip().split()\n"
        "    if len(parts) != 5:\n"
        "        return False\n"
        "    fields = [now.minute, now.hour, now.day, now.month, now.isoweekday() % 7]\n"
        "    for token, value in zip(parts, fields):\n"
        "        if token == '*':\n"
        "            continue\n"
        "        try:\n"
        "            allowed = {int(s) for s in token.split(',')}\n"
        "        except ValueError:\n"
        "            return False\n"
        "        if value not in allowed:\n"
        "            return False\n"
        "    return True\n"
        "\n"
        "\n"
        "def _post_to_fastapi(event: dict) -> tuple[bool, str]:\n"
        '    """POST the event to FastAPI. Returns (ok, message)."""\n'
        "    url = f'{_FASTAPI_URL}/events/{event[\"id\"]}/fire'\n"
        "    data = json.dumps(event).encode('utf-8')\n"
        "    req = urllib.request.Request(\n"
        "        url, data=data, method='POST',\n"
        "        headers={'Content-Type': 'application/json'},\n"
        "    )\n"
        "    try:\n"
        "        with urllib.request.urlopen(req, timeout=30) as resp:\n"
        "            body = resp.read().decode('utf-8', errors='replace')\n"
        "            return True, f'{resp.status}: {body[:200]}'\n"
        "    except urllib.error.HTTPError as exc:\n"
        "        return False, f'HTTP {exc.code}: {exc.reason}'\n"
        "    except urllib.error.URLError as exc:\n"
        "        return False, f'unreachable: {exc.reason}'\n"
        "    except Exception as exc:  # noqa: BLE001\n"
        "        return False, f'POST failed: {exc}'\n"
        "\n"
        "\n"
        "def loop() -> None:\n"
        "    seen_in_minute: set[tuple[str, str]] = set()\n"
        "    while True:\n"
        "        now = datetime.now().replace(second=0, microsecond=0)\n"
        "        minute_key = now.strftime('%Y-%m-%dT%H:%M')\n"
        "        for event in _load_events():\n"
        "            if not event.get('enabled', True):\n"
        "                continue\n"
        "            key = (event['id'], minute_key)\n"
        "            if key in seen_in_minute:\n"
        "                continue\n"
        "            if not _should_fire(event['schedule'], now):\n"
        "                continue\n"
        "            ts = datetime.now().isoformat(timespec='seconds')\n"
        "            print(\n"
        "                f'[cron {ts}] firing {event[\"id\"]!r} → '\n"
        "                f'POST {_FASTAPI_URL}/events/{event[\"id\"]}/fire'\n"
        "            )\n"
        "            ok, msg = _post_to_fastapi(event)\n"
        "            print(f'[cron {ts}]   {(\"ok\" if ok else \"FAIL\")}: {msg}')\n"
        "            seen_in_minute.add(key)\n"
        "        time.sleep(_POLL_S)\n"
        "\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    loop()\n"
    )
