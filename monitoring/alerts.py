#!/usr/bin/env python3
"""JARVIS alert bus.

Any module can call alerts.post(...) from any thread. The UI (or the plain CLI)
drains the queue and decides how to present it.

Levels
    info    soft pulse    - FYI (scheduled reminders, routine notifications, recoveries)
    warn    steady red    - needs attention soon (low battery, TTS/API trouble, stuck agent)
    urgent  fast flicker  - needs attention now (critical battery, brain offline, calls)

Approval gate
    alerts.request_approval("Run: rm -rf x?") blocks the calling thread until the
    user answers y/n (UI: single keypress; CLI: stdin). Silence for `timeout`
    seconds means NO. Dangerous actions are therefore denied by default.
"""
import os
import re
import sys
import time
import queue
import select
import threading
from dataclasses import dataclass, field

LEVELS = ("info", "warn", "urgent")

_q = queue.Queue()
_last = {}                      # dedup key -> last post time
_lock = threading.Lock()
_ui_approval = [None]           # UI registers a blocking approval handler here


@dataclass
class Alert:
    level: str
    text: str
    source: str = ""
    speak: bool = False
    t: float = field(default_factory=time.time)


def post(text, level="warn", source="", speak=False, dedup=60.0):
    """Queue an alert. Identical (source, text) alerts within `dedup` seconds are dropped."""
    level = level if level in LEVELS else "warn"
    text = str(text).strip()
    if not text:
        return False
    key = (source, text)
    now = time.time()
    with _lock:
        if dedup and now - _last.get(key, 0) < dedup:
            return False
        _last[key] = now
        if len(_last) > 500:    # keep the dedup table small
            for k in [k for k, v in _last.items() if now - v > 600]:
                _last.pop(k, None)
    _q.put(Alert(level, text, source, speak))
    return True


def pop():
    try:
        return _q.get_nowait()
    except queue.Empty:
        return None


# ───────────────────────── approval gate ─────────────────────────
def register_ui_approval(handler):
    """handler(text, timeout) -> bool, blocking. Pass None to unregister."""
    _ui_approval[0] = handler


def request_approval(text, timeout=60.0, source="safety"):
    """Block until the user approves (True) or denies/ignores (False)."""
    post(f"Approval needed: {text}", "urgent", source, speak=True, dedup=0)
    handler = _ui_approval[0]
    if handler is not None:
        try:
            return bool(handler(text, timeout))
        except Exception:
            return False
    # plain CLI fallback
    try:
        if not sys.stdin.isatty():
            return False
        print(f"\n[APPROVAL NEEDED] {text}\nApprove? [y/N] ({int(timeout)}s) > ", end="", flush=True)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            print("(no answer - denied)")
            return False
        return sys.stdin.readline().strip().lower() in ("y", "yes", "approve")
    except Exception:
        return False


# Commands that change or destroy things. Matching one triggers the approval gate.
_RISKY = re.compile(
    r"(?:^|[\s;&|(`])(?:"
    r"rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*|--recursive|--force)"
    r"|rmdir|shred|truncate|dd\s+|mkfs|fdisk|wipefs|format"
    r"|chmod\s+-R|chown\s+-R"
    r"|kill(?:all)?\s|pkill|killall"
    r"|shutdown|reboot|poweroff|halt"
    r"|pm\s+(?:uninstall|clear|disable|hide)"
    r"|pkg\s+(?:uninstall|remove|purge)|apt(?:-get)?\s+(?:remove|purge)|pip3?\s+uninstall"
    r"|git\s+(?:push\s+.*--force|push\s+-f|reset\s+--hard|clean\s+-[a-z]*f)"
    r"|su\b|sudo\b|tsu\b"
    r"|svc\s+(?:wifi|data)\s+disable"
    r")|>\s*/(?:dev|sdcard|storage)/|curl[^|]*\|\s*(?:ba)?sh|wget[^|]*\|\s*(?:ba)?sh"
    r"|(?:drop|truncate)\s+(?:table|database)",
    re.IGNORECASE,
)


def is_risky_command(cmd):
    return bool(_RISKY.search(str(cmd or "")))


# ───────────────────────── notification triage ─────────────────────────
_URGENT_NOTIF = re.compile(
    r"\b(?:incoming call|missed call|calling you|urgent|emergency|asap|"
    r"security alert|suspicious|unauthorized|unauthorised|fraud|"
    r"battery (?:low|critical)|overheat\w*)\b",
    re.IGNORECASE,
)
_PRIORITY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "priority_contacts.txt",
)


def _priority_names():
    try:
        with open(_PRIORITY_FILE, encoding="utf-8") as f:
            return [ln.strip().lower() for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError:
        return []


def classify_notification(text):
    """'urgent' for calls / security / priority contacts, else 'info' (gentle cue)."""
    low = str(text).lower()
    if _URGENT_NOTIF.search(low):
        return "urgent"
    for name in _priority_names():
        if name and name in low:
            return "urgent"
    return "info"
