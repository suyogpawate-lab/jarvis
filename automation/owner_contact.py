"""Local Android owner-call bridge.

Any JARVIS subsystem can request a local Telecom call without SIM, carrier,
or remote telephony provider. Android owns the actual call UI and lifecycle.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from pathlib import Path


class OwnerContactManager:
    """Small, thread-safe client for the Android companion's local call bridge."""

    def __init__(self, host="127.0.0.1", port=None, state_path="data/owner_contact/events.json"):
        self.host = str(host)
        self.port = int(port or os.environ.get("JARVIS_OWNER_CALL_PORT", "21342"))
        self.state_path = Path(state_path)
        self._lock = threading.RLock()

    def _recent_events(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def _save_events(self, rows):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows[-300:], ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.state_path)

    def _send(self, payload):
        raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with socket.create_connection((self.host, self.port), timeout=2.5) as conn:
            conn.settimeout(3.0)
            conn.sendall(raw)
            chunks = []
            while True:
                part = conn.recv(4096)
                if not part:
                    break
                chunks.append(part)
                if b"\n" in part:
                    break
        response = b"".join(chunks).split(b"\n", 1)[0]
        if not response:
            raise RuntimeError("Android owner-call bridge returned an empty response.")
        result = json.loads(response.decode("utf-8"))
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError(str(result.get("error", "Android owner-call request failed")) if isinstance(result, dict) else "Invalid Android response")
        return result

    def request_call(self, reason, message, priority="normal", source="jarvis",
                     event_id=None, dedupe_seconds=600):
        """Request one local incoming-call session; duplicate event IDs are suppressed."""
        reason = " ".join(str(reason or "assistant_update").split())[:100]
        message = " ".join(str(message or "").split())[:1200]
        priority = str(priority or "normal").lower()
        if priority not in {"low", "normal", "high", "urgent"}:
            raise ValueError("priority must be low, normal, high, or urgent")
        if not message:
            raise ValueError("message must not be empty")
        identity = str(event_id or f"{source}:{reason}:{message}")
        fingerprint = hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()
        now = time.time()
        with self._lock:
            rows = [x for x in self._recent_events()
                    if now - float(x.get("at", 0)) < max(60, int(dedupe_seconds))]
            if any(x.get("fingerprint") == fingerprint for x in rows):
                return {"ok": True, "duplicate": True, "delivered": False}
            result = self._send({
                "action": "call",
                "reason": reason,
                "message": message,
                "priority": priority,
                "source": str(source or "jarvis")[:80],
                "event_id": fingerprint[:24],
            })
            rows.append({"fingerprint": fingerprint, "at": now, "reason": reason})
            self._save_events(rows)
            return {"ok": True, "duplicate": False, "delivered": True, "android": result}

    def schedule_wakeup(self, at_epoch, message="JARVIS wake-up call", event_id=None):
        """Schedule a device-side alarm; it does not depend on Termux staying alive."""
        timestamp = float(at_epoch)
        if timestamp <= time.time():
            raise ValueError("Wake-up time must be in the future.")
        return self._send({
            "action": "schedule_wakeup",
            "at_epoch": timestamp,
            "message": " ".join(str(message).split())[:500],
            "event_id": str(event_id or f"wake-{int(timestamp)}")[:100],
        })

    def cancel_wakeup(self, event_id):
        return self._send({"action": "cancel_wakeup", "event_id": str(event_id)[:100]})

    def status(self):
        try:
            result = self._send({"action": "status"})
            return {"ok": True, **result}
        except Exception as exc:
            return {"ok": False, "available": False, "error": type(exc).__name__}


__all__ = ["OwnerContactManager"]
