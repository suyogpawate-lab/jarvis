"""Durable execution telemetry and conservative retry policy for JARVIS.

This layer wraps the existing dispatcher; it does not bypass tool contracts,
command guards, contact resolution, or destructive-action confirmations.
Only clearly read-only requests may be retried, and only for transient failures.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JOURNAL = ROOT / "data" / "agent_events.jsonl"
MAX_EVENT_RESULT = 500
MAX_HISTORY = 100

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b(?:gsk_[A-Za-z0-9]{12,}|AIza[A-Za-z0-9_-]{20,})\b"),
)
_TRANSIENT_MARKERS = (
    "timed out", "timeout", "temporarily unavailable", "connection reset",
    "connection aborted", "http 429", "http 500", "http 502", "http 503",
    "rate limit", "rate-limit", "try again",
)
_READ_ONLY_NATURAL = re.compile(
    r"^\s*(?:/doctor\b|/health\b|show\b|list\b|check\b|inspect\b|read\b|"
    r"search\b|find\b|summari[sz]e\b|what\b|who\b|when\b|where\b|"
    r"how many\b|get\b|report\b|status\b|display\b|explain\b|tell me\b)",
    re.IGNORECASE,
)
_READ_ONLY_SHELL = re.compile(
    r"^\s*(?:pwd|ls|stat|file|head|tail|cat|less|wc|grep|rg|find|du|df|free|"
    r"ps|top|uptime|whoami|id|date|uname|git\s+(?:status|log|diff|show)|"
    r"python\s+-m\s+(?:unittest|pytest))(?:\s|$)",
    re.IGNORECASE,
)


def redact(value: Any, limit: int = MAX_EVENT_RESULT) -> str:
    """Bound event payloads and mask common credential formats."""
    text = str(value if value is not None else "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def is_read_only_request(command: str) -> bool:
    """Conservative allow-list: unknown actions are never retried automatically."""
    text = str(command or "").strip()
    return bool(_READ_ONLY_NATURAL.match(text) or _READ_ONLY_SHELL.match(text))


def is_transient_failure(result: Any) -> bool:
    """Return true only when a failed result looks recoverable."""
    if isinstance(result, dict):
        if not (result.get("error") or result.get("ok") is False):
            return False
        text = str(result.get("error", result))
    else:
        text = str(result or "")
    lowered = text.lower()
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)


def is_failure_result(result: Any) -> bool:
    if result is None:
        return True
    if isinstance(result, dict):
        if result.get("error") or result.get("ok") is False:
            return True
        for key in ("exit", "exit_code", "returncode"):
            if key in result:
                try:
                    if int(result[key]) != 0:
                        return True
                except (TypeError, ValueError):
                    return True
        return False
    text = str(result).strip()
    if not text:
        return True
    upper = text.upper()
    if upper.startswith(("[ERROR]", "[FAIL]", "[FAILED]", "[BLOCKED]", "[NEEDS_APPROVAL]")):
        return True
    match = re.search(r"(?m)^\[EXIT\]\s*(-?\d+)\s*$", text)
    return bool(match and int(match.group(1)) != 0)


class ExecutionJournal:
    """Append-only, bounded, best-effort event journal stored with private perms."""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else DEFAULT_JOURNAL
        self._lock = threading.Lock()

    def record(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload["timestamp"] = time.time()
        for key in ("command", "result", "error"):
            if key in payload:
                payload[key] = redact(payload[key])
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.write(fd, line.encode("utf-8", errors="replace"))
                finally:
                    os.close(fd)
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
        except OSError:
            # Telemetry must never make a working user action fail.
            return

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            bounded = max(1, min(int(limit), MAX_HISTORY))
        except (TypeError, ValueError):
            bounded = 20
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-bounded:]
        except OSError:
            return []
        events = []
        for line in lines:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(value)
            except (ValueError, TypeError):
                continue
        return events


class ExecutionRuntime:
    """Observable dispatch wrapper with safe, bounded transient retries."""

    def __init__(
        self,
        dispatch: Callable[[str], Any],
        journal_path: str | os.PathLike | None = None,
        max_attempts: int = 2,
        retry_delay: float = 0.25,
    ):
        self.dispatch = dispatch
        self.journal = ExecutionJournal(journal_path)
        self.max_attempts = max(1, min(int(max_attempts), 2))
        self.retry_delay = max(0.0, min(float(retry_delay), 1.0))

    def execute(self, task_id: str, step: dict[str, Any]) -> Any:
        command = str(step.get("command", "")).strip()
        number = step.get("number")
        safe_retry = is_read_only_request(command)
        attempts_allowed = self.max_attempts if safe_retry else 1
        result: Any = None
        for attempt in range(1, attempts_allowed + 1):
            started = time.time()
            self.journal.record({
                "event": "step_started", "task_id": task_id,
                "step": number, "attempt": attempt, "command": command,
            })
            try:
                result = self.dispatch(command)
            except Exception as exc:
                result = f"[ERROR] {type(exc).__name__}: {exc}"
            failed = is_failure_result(result)
            self.journal.record({
                "event": "step_finished", "task_id": task_id,
                "step": number, "attempt": attempt,
                "status": "FAILED" if failed else "COMPLETED",
                "duration_ms": round((time.time() - started) * 1000),
                "result": result if isinstance(result, (str, int, float, bool, dict, list)) else repr(result),
            })
            if not failed or attempt >= attempts_allowed or not is_transient_failure(result):
                break
            if self.retry_delay:
                time.sleep(self.retry_delay)
        return result

    def history_text(self, limit: int = 20) -> str:
        events = self.journal.recent(limit)
        if not events:
            return "[AGENT HISTORY] No execution events recorded yet."
        lines = ["[AGENT HISTORY] Recent workflow events (credentials redacted):"]
        for item in events:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.get("timestamp", 0)))
            task = item.get("task_id", "-")
            step = item.get("step", "-")
            attempt = item.get("attempt", 1)
            event = item.get("event", "event")
            status = item.get("status", "")
            detail = item.get("result", item.get("command", item.get("error", "")))
            lines.append(f"{when} | {task} step {step} try {attempt} | {event} {status} | {redact(detail, 160)}")
        return "\n".join(lines)
