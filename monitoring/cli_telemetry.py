"""Privacy-conscious metrics for the plain JARVIS CLI.

No prompts, responses, tool arguments, credentials, or personal data are stored.
The full-screen Termux UI and web UI do not render this summary.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_EVENT_FILE = _ROOT / "data" / "cli_telemetry.jsonl"
_LOCK = threading.RLock()
_SESSION_STARTED = time.monotonic()
_SESSION = {
    "input_tokens": 0, "output_tokens": 0, "model_calls": 0,
    "turns": 0, "tool_calls": 0, "tool_successes": 0,
}
_CURRENT = None


def _emit(event: str, payload: dict) -> None:
    if os.getenv("JARVIS_CLI_TELEMETRY", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    try:
        _EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {"event": event, "time": time.time(), "data": payload}
        with _EVENT_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Telemetry must never interrupt an assistant interaction.
        pass


def begin_turn() -> None:
    global _CURRENT
    with _LOCK:
        _CURRENT = {
            "input_tokens": 0, "output_tokens": 0, "model_calls": 0,
            "tools": [], "tool_total": 0, "tool_successes": 0,
            "verified_total": 0, "verified_successes": 0,
        }


def record_model_usage(provider: str, model: str, usage, latency_ms: float) -> None:
    if not isinstance(usage, dict):
        return
    def count(*keys):
        for key in keys:
            value = usage.get(key)
            try:
                number = int(value)
                if number >= 0:
                    return number
            except (TypeError, ValueError):
                continue
        return 0
    incoming = count("prompt_tokens", "input_tokens")
    outgoing = count("completion_tokens", "output_tokens")
    with _LOCK:
        _SESSION["input_tokens"] += incoming
        _SESSION["output_tokens"] += outgoing
        _SESSION["model_calls"] += 1
        if _CURRENT is not None:
            _CURRENT["input_tokens"] += incoming
            _CURRENT["output_tokens"] += outgoing
            _CURRENT["model_calls"] += 1
    _emit("model.usage", {
        "provider": str(provider)[:40], "model": str(model)[:100],
        "input_tokens": incoming, "output_tokens": outgoing,
        "latency_ms": round(max(0.0, float(latency_ms)), 1),
    })


def record_tool_usage(name: str, result) -> None:
    success = True
    verified = None
    if isinstance(result, dict):
        success = not bool(result.get("error")) and result.get("ok") is not False
        if isinstance(result.get("verified"), bool):
            verified = result["verified"]
    elif result is None:
        success = False
    elif isinstance(result, str):
        upper = result.strip().upper()
        success = not upper.startswith(("[ERROR]", "[FAILED]", "[BLOCKED]"))
    label = str(name or "unknown")[:100]
    with _LOCK:
        _SESSION["tool_calls"] += 1
        if success:
            _SESSION["tool_successes"] += 1
        if _CURRENT is not None:
            _CURRENT["tool_total"] += 1
            if success:
                _CURRENT["tool_successes"] += 1
            if verified is not None:
                _CURRENT["verified_total"] += 1
                if verified and success:
                    _CURRENT["verified_successes"] += 1
            if label not in _CURRENT["tools"]:
                _CURRENT["tools"].append(label)
    _emit("tool.result", {"name": label, "success": success, "verified": verified})


def finish_turn(elapsed_seconds: float) -> dict:
    with _LOCK:
        current = dict(_CURRENT or {})
        _SESSION["turns"] += 1
        snapshot = dict(_SESSION)
    total = int(current.get("verified_total", 0))
    verified = int(current.get("verified_successes", 0))
    return {
        "elapsed_seconds": round(max(0.0, float(elapsed_seconds)), 2),
        "session_seconds": round(time.monotonic() - _SESSION_STARTED, 1),
        "input_tokens": int(current.get("input_tokens", 0)),
        "output_tokens": int(current.get("output_tokens", 0)),
        "session_input_tokens": snapshot["input_tokens"],
        "session_output_tokens": snapshot["output_tokens"],
        "model_calls": int(current.get("model_calls", 0)),
        "tools": list(current.get("tools", [])),
        "tool_total": int(current.get("tool_total", 0)),
        "tool_successes": int(current.get("tool_successes", 0)),
        "verified_total": total,
        "verified_successes": verified,
        "verification_percent": round(100 * verified / total) if total else None,
        "session_turns": snapshot["turns"],
    }


def format_cli_summary(summary: dict) -> str:
    elapsed = summary.get("elapsed_seconds", 0)
    live = int(summary.get("session_seconds", 0))
    minutes, seconds = divmod(live, 60)
    hours, minutes = divmod(minutes, 60)
    live_text = f"{hours}h {minutes}m" if hours else f"{minutes}m {seconds}s"
    tools = ", ".join(summary.get("tools") or []) or "none"
    verification = summary.get("verification_percent")
    if verification is None:
        verify_text = "not scored (no explicit verified tool result)"
    else:
        verify_text = (
            f"{summary.get('verified_successes')}/{summary.get('verified_total')} "
            f"explicitly verified ({verification}%)"
        )
    return (
        f"[CLI METRICS] turn {elapsed:.2f}s | session {live_text} | "
        f"tokens {summary.get('input_tokens', 0)} in / {summary.get('output_tokens', 0)} out\n"
        f"  tools: {tools} | tool success {summary.get('tool_successes', 0)}/"
        f"{summary.get('tool_total', 0)} | verification: {verify_text}\n"
        f"  session totals: {summary.get('session_input_tokens', 0)} in / "
        f"{summary.get('session_output_tokens', 0)} out across "
        f"{summary.get('session_turns', 0)} turns"
    )
