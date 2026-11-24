"""Thread-safe live token usage state shared by the CLI and web HUD."""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_STATE = {
    "provider": None, "model": None, "phase": "idle",
    "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
    "error": None, "started_at": None, "updated_at": None,
}


def request_started(provider: str, model: str, phase: str = "completion") -> None:
    with _LOCK:
        _STATE.update({
            "provider": str(provider), "model": str(model), "phase": "running",
            "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
            "error": None, "started_at": time.time(), "updated_at": time.time(),
        })


def request_completed(provider: str, model: str, usage: dict | None, phase: str = "completion") -> None:
    usage = usage or {}
    with _LOCK:
        _STATE.update({
            "provider": str(provider), "model": str(model), "phase": "complete",
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "error": None, "updated_at": time.time(),
        })


def request_failed(provider: str, model: str, phase: str, error: str) -> None:
    with _LOCK:
        _STATE.update({
            "provider": str(provider), "model": str(model), "phase": "error",
            "error": str(error)[:240], "updated_at": time.time(),
        })


def snapshot() -> dict:
    with _LOCK:
        return dict(_STATE)
