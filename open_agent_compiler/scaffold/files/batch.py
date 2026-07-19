"""Generator for runners/ — the non-realtime batch execution path.

The realtime tier (telegram bot / FastAPI chat) answers in-process; the
batch runners are the other lane: a jobs file in, compiled workers run
to completion through the harness adapter, JSONL results out. Pairs
with the cron template (cron fires events on a schedule; the batch
runner drains a work list on demand).
"""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render_jobs_sample(config: ScaffoldConfig) -> str:
    return (
        "[\n"
        '  {"agent": "primary", "prompt": "Introduce yourself in one sentence."},\n'
        '  {"agent": "primary", "prompt": "List three things you can help with."}\n'
        "]\n"
    )


def render_batch_runner(config: ScaffoldConfig) -> str:
    return (
        '"""Batch-run compiled workers over a jobs file (non-realtime lane).\n'
        "\n"
        "    uv run python runners/batch.py               # runners/jobs.json\n"
        "    uv run python runners/batch.py my_jobs.json  # custom jobs file\n"
        "\n"
        "Each job is {\"agent\": <compiled agent name>, \"prompt\": <task>}.\n"
        "Results append to runners/results.jsonl — one JSON object per job\n"
        "with the output or the surfaced harness error. Jobs run through\n"
        "app.harness, so the same file works on whatever dialect this\n"
        "project compiles for.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "import json\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        "\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
        "\n"
        "from app.harness import run_compiled_agent  # noqa: E402\n"
        "\n"
        "HERE = Path(__file__).resolve().parent\n"
        'RESULTS = HERE / "results.jsonl"\n'
        "\n"
        "\n"
        "def main() -> None:\n"
        '    jobs_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "jobs.json"\n'
        "    jobs = json.loads(jobs_path.read_text())\n"
        "    with RESULTS.open(\"a\") as sink:\n"
        "        for i, job in enumerate(jobs, 1):\n"
        '            agent = str(job.get("agent", "primary"))\n'
        '            prompt = str(job.get("prompt", ""))\n'
        "            started = time.time()\n"
        "            try:\n"
        "                output = run_compiled_agent(agent, prompt)\n"
        "                record = {\"agent\": agent, \"prompt\": prompt,\n"
        "                          \"output\": output, \"error\": None}\n"
        "            except Exception as exc:  # a failed job is data, not a crash\n"
        "                record = {\"agent\": agent, \"prompt\": prompt,\n"
        "                          \"output\": None, \"error\": str(exc)}\n"
        "            record[\"elapsed_s\"] = round(time.time() - started, 2)\n"
        "            sink.write(json.dumps(record) + \"\\n\")\n"
        "            status = \"ok\" if record[\"error\"] is None else \"FAILED\"\n"
        "            print(f\"[{i}/{len(jobs)}] {agent}: {status}\")\n"
        "    print(f\"results -> {RESULTS}\")\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    main()\n"
    )
