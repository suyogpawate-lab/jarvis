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


def _classify_window_intent(prompt):
    """Return a strict workspace intent only when the user says window/panel/workspace."""
    import re
    from urllib.parse import urlsplit

    text = str(prompt or "").strip()
    low = text.lower()

    # Window-management language must explicitly refer to a workspace window.
    control = re.match(
        r"^(?:please\s+)?(minimize|restore|close|maximize|focus)\s+(?:(?:the|all|my)\s+)?(.+?)\s+(?:windows?|panels?|surfaces?)\s*[.!?]*$",
        low,
    )
    if control:
        action, target = control.groups()
        if target in {"all", "my", "the", "all the", "all my"}:
            target = ""
        return {"action": "control", "command": action, "title": target}

    if re.fullmatch(r"(?:please\s+)?(?:close|minimize|restore|maximize|focus)\s+all\s+(?:the\s+)?windows?[.!?]*", low):
        action = re.match(r"(?:please\s+)?(close|minimize|restore)", low).group(1)
        return {"action": "control", "command": action, "title": ""}

    explicit_window = bool(re.search(
        r"\b(?:floating\s+window|window|panel|workspace|on the orb|inside the orb)\b",
        low,
    ))
    if not explicit_window:
        return None

    url_match = re.search(r"https?://[^\s<>]+", text, re.I)
    url = url_match.group(0).rstrip(".,);]") if url_match else ""
    if url:
        parsed = urlsplit(url)
        host, path = (parsed.hostname or "").lower(), parsed.path.lower()
        if host == "youtu.be" or host.endswith("youtube.com"):
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
        return {"action": "open", "kind": kind, "title": title, "url": url}

    if re.search(r"\b(?:live\s+screen|screen\s+feed|current\s+screen|screen\s+cast)\b", low):
        return {"action": "open", "kind": "live_screen", "title": "Live Perception", "url": ""}
    if re.search(r"\b(?:terminal|command\s+output|execution\s+log)\b", low):
        return {"action": "open", "kind": "terminal", "title": "Live Execution", "url": ""}
    if re.search(r"\b(?:task|tasks|activity|progress)\b", low):
        return {"action": "open", "kind": "task", "title": "JARVIS Activity", "url": ""}
    if re.search(r"\b(?:tools|connectors)\b", low):
        return {"action": "open", "kind": "tools", "title": "Tools & Connectors", "url": ""}
    if re.search(r"\b(?:telemetry|token usage|confidence)\b", low):
        return {"action": "open", "kind": "telemetry", "title": "Live Telemetry", "url": ""}
    return None


def route_prompt(prompt):
    """Route only unambiguous, explicitly requested workspace-window actions."""
    intent = _classify_window_intent(prompt)
    if not intent:
        return False
    if intent["action"] == "control":
        _emit("surface.command", {"action": intent["command"], "title": intent["title"]})
    else:
        _emit("surface.open", {
            "kind": intent["kind"], "title": intent["title"],
            "url": intent["url"], "metadata": {},
        })
    return True


def open_surface(kind, title, url=""):
    """Queue a typed workspace surface request for the local workspace server."""
    allowed = {"web", "browser", "youtube", "video", "image", "pdf", "audio",
               "document", "live_screen", "terminal", "task", "tools", "telemetry"}
    kind = str(kind or "").lower()
    if kind not in allowed:
        return {"ok": False, "error": "Unsupported workspace surface type."}
    _emit("surface.open", {"kind": kind, "title": str(title or kind)[:120],
                           "url": str(url or "")[:2048], "metadata": {}})
    return {"ok": True, "queued": True, "kind": kind,
            "message": "Workspace window request queued."}


def control_surface(action, title=""):
    """Queue a window-management request; never controls Android applications."""
    action = str(action or "").lower()
    if action not in {"minimize", "restore", "close", "maximize", "focus"}:
        return {"ok": False, "error": "Supported window actions: minimize, restore, maximize, focus, close."}
    _emit("surface.command", {"action": action, "title": str(title or "")[:120]})
    return {"ok": True, "queued": True, "action": action, "title": str(title or "")[:120]}


def list_surfaces():
    """Read the local workspace snapshot; no app or device state is queried."""
    import json
    from urllib.request import urlopen
    try:
        with urlopen("http://127.0.0.1:8767/api/snapshot", timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
        return {"ok": True, "surfaces": data.get("surfaces", [])}
    except Exception as exc:
        return {"ok": False, "error": "Workspace is not available (" + type(exc).__name__ + ")."}
