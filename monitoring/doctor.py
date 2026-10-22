"""Unified, local-first JARVIS diagnostics. Never prints secret values."""
from __future__ import annotations

import importlib.util
import os
import shutil
import socket
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


def _check(name, status, detail):
    return {"name": name, "status": status, "detail": str(detail)}


def run_doctor(section="all"):
    """Return structured diagnostics for display and tests; no network by default."""
    section = (section or "all").strip().lower()
    rows = []
    if section not in {"all", "local", "providers", "voice", "mcp"}:
        return [_check("doctor", "error", "Use all, local, providers, voice, or mcp.")]

    if section in {"all", "local"}:
        rows.append(_check("python", "ok", __import__("sys").version.split()[0]))
        for name in ("termux-battery-status", "termux-microphone-record", "ffmpeg", "git"):
            rows.append(_check(name, "ok" if shutil.which(name) else "unavailable",
                               shutil.which(name) or "not found on PATH"))
        try:
            from monitoring.system_telemetry import get_telemetry
            t = get_telemetry()
            mem = t.get("memory", {})
            rows.append(_check("telemetry", "ok" if mem.get("total") else "degraded",
                               "RAM {}/{} MiB; swap {}/{} MiB".format(
                                   int(mem.get("used", 0) / 1048576),
                                   int(mem.get("total", 0) / 1048576),
                                   int(mem.get("swap_used", 0) / 1048576),
                                   int(mem.get("swap_total", 0) / 1048576))))
        except Exception as exc:
            rows.append(_check("telemetry", "error", type(exc).__name__))

    if section in {"all", "providers"}:
        for provider, names in (
            ("Groq", ("GROQ_API_KEYS", "GROQ_API_KEY")),
            ("Gemini", ("GEMINI_API_KEYS", "GEMINI_API_KEY")),
            ("Claude", ("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY")),
            ("OmniRoute", ("OMNIROUTE_API_KEY",)),
        ):
            configured = any(os.getenv(key, "").strip() for key in names)
            rows.append(_check(provider, "configured" if configured else "missing",
                               "credential present (value hidden)" if configured else "no credential configured"))
        base = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
        u = urlparse(base)
        if u.hostname:
            try:
                with socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 80)), timeout=1.5):
                    status, detail = "reachable", "TCP endpoint reachable"
            except OSError:
                status, detail = "unavailable", "TCP endpoint not reachable"
            rows.append(_check("OmniRoute endpoint", status, detail))

    if section in {"all", "voice"}:
        for name, path in (("Needle runner", "android-arm64/needle"),
                           ("Whistle model", "whistle.cact")):
            asset = ROOT / path
            if not asset.is_file():
                status, detail = "missing", path
            elif name == "Needle runner" and not os.access(asset, os.X_OK):
                status, detail = "unavailable", path + " (not executable)"
            else:
                status, detail = "ok", path
            rows.append(_check(name, status, detail))
        try:
            importlib.util.find_spec("openwakeword")
            available = importlib.util.find_spec("openwakeword") is not None
            rows.append(_check("OpenWakeWord", "ok" if available else "unavailable",
                               "module available" if available else "optional dependency missing"))
        except (ImportError, ValueError):
            rows.append(_check("OpenWakeWord", "unavailable", "optional dependency missing"))

    if section in {"all", "mcp"}:
        rows.append(_check("MCP", "configured" if (ROOT / "config/mcp_servers.json").is_file() else "unknown",
                           "server config presence only; connection is not probed"))

    return rows


def format_doctor(section="all"):
    rows = run_doctor(section)
    lines = ["JARVIS DOCTOR"]
    for item in rows:
        lines.append("[{:<11}] {} — {}".format(item["status"].upper(), item["name"], item["detail"]))
    counts = {}
    for item in rows:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    lines.append("Summary: " + ", ".join("{} {}".format(n, k) for k, n in sorted(counts.items())))
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_doctor())
