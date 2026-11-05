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

def presence_update(state):
    _emit("presence.update", {"state": str(state)[:20]})


def route_prompt(prompt):
    """Route explicit visual and window-management commands to the workspace."""
    from urllib.parse import urlsplit
    text = str(prompt or "").strip()
    low = text.lower()

    for action in ("minimize", "restore", "close"):
        prefix = action + " "
        if low.startswith(prefix) and low.endswith(" windows"):
            target = low[len(prefix):-len(" windows")].strip()
            if target in ("all", "the", ""):
                target = ""
            _emit("surface.command", {"action": action, "title": target})
            return True
        if low in (action + " all windows", action + " the windows"):
            _emit("surface.command", {"action": action, "title": ""})
            return True
        if low.startswith(prefix) and low.endswith(" window"):
            target = text[len(prefix):-len(" window")].strip()
            if target.startswith("the "):
                target = target[4:]
            _emit("surface.command", {"action": action, "title": target})
            return True

    prefixes = ("show ", "open ", "display ", "play ",
                "please show ", "please open ", "please display ", "please play ")
    if not low.startswith(prefixes):
        return False
    url = next((part.rstrip(".,)") for part in text.split()
                if part.startswith(("https://", "http://"))), "")
    if not url:
        return False
    parsed = urlsplit(url)
    host, path = parsed.hostname or "", parsed.path.lower()
    if "youtube.com" in host or host.endswith("youtu.be"):
        kind = "youtube"
    elif path.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        kind = "image"
    elif path.endswith((".mp4", ".webm", ".mov", ".m4v")):
        kind = "video"
    elif path.endswith(".pdf"):
        kind = "pdf"
    elif path.endswith((".mp3", ".m4a", ".ogg", ".wav")):
        kind = "audio"
    else:
        kind = "web"
    title = {"youtube": "YouTube", "image": "Image", "video": "Video",
             "pdf": "Document", "audio": "Audio", "web": "Browser"}[kind]
    _emit("surface.open", {"kind": kind, "title": title, "url": url, "metadata": {}})
    return True
