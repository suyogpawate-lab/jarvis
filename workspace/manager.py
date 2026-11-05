"""JARVIS multi-surface workspace state manager.

The manager is deliberately UI-agnostic. It stores bounded, sanitized surface
metadata and task telemetry; it never stores screen pixels, credentials, or
arbitrary command output.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from urllib.parse import urlsplit
import ipaddress

MAX_SURFACES = 6
KINDS = {"web", "browser", "youtube", "video", "image", "pdf", "audio", "document", "live_screen", "terminal", "task", "tools", "telemetry"}
STATUSES = {"active", "minimized", "paused", "waiting", "complete", "error"}
_LABEL = re.compile(r"[^\w .()\-:/]{1,}", re.UNICODE)


def _clean_text(value, limit=120):
    return _LABEL.sub("", str(value or "")).strip()[:limit]


def _safe_url(value):
    value = str(value or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only http(s) URLs are supported")
    host = parsed.hostname.lower().rstrip(".")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not allowed")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local network URLs are not allowed in embedded surfaces")
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            raise ValueError("Private and reserved IP addresses are not allowed in embedded surfaces")
    except ValueError as exc:
        if "not allowed" in str(exc):
            raise
    return value[:2048]


class WorkspaceManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._surfaces = {}
        self._tasks = {}
        self._events = []
        self._seq = 0
        self._started = time.monotonic()
        self._telemetry = {"input_tokens": None, "output_tokens": None,
                           "model": None, "confidence": None, "tools": []}
        self._presence = "standby"

    def _emit(self, event, payload):
        self._seq += 1
        self._events.append({"id": self._seq, "event": event, "data": payload, "time": time.time()})
        del self._events[:-200]

    def open_surface(self, kind, title, url="", metadata=None):
        kind = str(kind or "").lower()
        if kind not in KINDS:
            raise ValueError("Unsupported surface type")
        title = _clean_text(title) or kind.replace("_", " ").title()
        if kind in {"web", "browser", "youtube", "video", "image", "pdf", "audio", "document"}:
            url = _safe_url(url)
        else:
            url = ""
        with self._lock:
            if len(self._surfaces) >= MAX_SURFACES:
                raise OverflowError("Workspace is full (maximum six surfaces)")
            sid = uuid.uuid4().hex[:12]
            surface = {"id": sid, "kind": kind, "title": title, "url": url,
                       "status": "active", "created_at": time.time(),
                       "metadata": metadata if isinstance(metadata, dict) else {}}
            self._surfaces[sid] = surface
            self._emit("surface.open", surface.copy())
            return surface.copy()

    def close_surface(self, sid):
        with self._lock:
            item = self._surfaces.pop(str(sid), None)
            if item:
                self._emit("surface.close", {"id": sid})
            return bool(item)

    def update_surface(self, sid, changes):
        with self._lock:
            item = self._surfaces.get(str(sid))
            if not item:
                return None
            if "status" in changes:
                status = str(changes["status"])
                if status not in STATUSES:
                    raise ValueError("Invalid status")
                item["status"] = status
            if "title" in changes:
                item["title"] = _clean_text(changes["title"])
            self._emit("surface.update", item.copy())
            return item.copy()

    def control_surfaces(self, action, title=None):
        """Apply a JARVIS window command to matching surfaces."""
        action = str(action or "").lower()
        if action not in {"minimize", "restore", "close"}:
            raise ValueError("Unsupported surface command")
        target = _clean_text(title, 120).lower()
        with self._lock:
            matches = [x for x in self._surfaces.values()
                       if not target or target in x["title"].lower()]
            changed = []
            for item in matches:
                sid = item["id"]
                if action == "close":
                    self._surfaces.pop(sid, None)
                    self._emit("surface.close", {"id": sid})
                else:
                    item["status"] = "minimized" if action == "minimize" else "active"
                    self._emit("surface.update", item.copy())
                changed.append(sid)
            return changed

    def presence(self, state):
        state = str(state or "standby").lower()
        if state not in {"standby", "listening", "thinking", "speaking", "alert"}:
            state = "standby"
        with self._lock:
            if state != self._presence:
                self._presence = state
                self._emit("presence.update", {"state": state})
            return self._presence

    def task_event(self, task_id, name, status="active", detail=""):
        if status not in STATUSES:
            raise ValueError("Invalid task status")
        task_id = _clean_text(task_id, 64) or uuid.uuid4().hex[:12]
        item = {"id": task_id, "name": _clean_text(name), "status": status,
                "detail": _clean_text(detail, 300), "updated_at": time.time()}
        with self._lock:
            self._tasks[task_id] = item
            self._emit("task.update", item.copy())
        return item

    def telemetry(self, values):
        with self._lock:
            for key in ("input_tokens", "output_tokens"):
                value = values.get(key)
                if isinstance(value, int) and 0 <= value <= 100_000_000:
                    self._telemetry[key] = value
            if "model" in values:
                self._telemetry["model"] = _clean_text(values["model"], 100)
            if "confidence" in values:
                value = values["confidence"]
                if isinstance(value, (int, float)) and 0 <= value <= 1:
                    self._telemetry["confidence"] = round(float(value), 3)
            if isinstance(values.get("tools"), list):
                self._telemetry["tools"] = [_clean_text(x, 80) for x in values["tools"][:30]]
            self._emit("telemetry.update", self._telemetry.copy())
            return self._telemetry.copy()

    def snapshot(self):
        with self._lock:
            return {"surfaces": [x.copy() for x in self._surfaces.values()],
                    "tasks": [x.copy() for x in self._tasks.values()],
                    "telemetry": self._telemetry.copy(),
                    "jarvis_state": self._presence,
                    "uptime_seconds": round(time.monotonic() - self._started, 1),
                    "sequence": self._seq}

    def events_after(self, seq):
        with self._lock:
            return [x.copy() for x in self._events if x["id"] > int(seq)]
