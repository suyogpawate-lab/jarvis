"""Small, privacy-conscious event bridge from the JARVIS UI to the workspace.

Only task metadata is written. Prompts, replies, screen contents, credentials,
and terminal output are deliberately excluded.
"""
import json
import os
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_EVENT_FILE = _ROOT / "data" / "workspace_events.jsonl"


def _emit(event, payload):
    try:
        _EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {"event": event, "data": payload, "time": time.time()}
        with _EVENT_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Workspace telemetry must never break the primary JARVIS interaction.
        pass


def task_started(task_id, prompt, source="typed"):
    # Do not persist prompt text; it may contain private information.
    _emit("task.update", {"id": str(task_id), "name": "JARVIS task",
                          "status": "active", "detail": "Started via " + str(source)[:20]})


def task_finished(task_id, status="complete", detail=""):
    if status not in ("complete", "error", "waiting", "paused"):
        status = "complete"
    _emit("task.update", {"id": str(task_id), "name": "JARVIS task",
                          "status": status, "detail": str(detail)[:120]})
