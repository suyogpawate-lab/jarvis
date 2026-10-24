"""Read-only health diagnostics for JARVIS on Android/Termux.

No provider APIs are called and no secret values are printed.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {
    "Groq": ("GROQ_API_KEYS", "GROQ_API_KEY"),
    "Gemini": ("GEMINI_API_KEYS", "GEMINI_API_KEY"),
    "Anthropic": ("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY"),
    "OmniRoute": ("OMNIROUTE_API_KEY", "OMNIROUTE_BASE_URL"),
}
SERVICES = (
    ("OmniRoute", "127.0.0.1", 20128),
    ("Knowledge Hub", "127.0.0.1", 8766),
    ("WhatsApp bridge", "127.0.0.1", 23841),
    ("Ollama", "127.0.0.1", 11434),
)
REQUIRED_FILES = (
    "jarvis.py",
    "jarvis_ui.py",
    "core/core.py",
    "automation/command_dispatcher.py",
    "config/abilities.json",
    "monitoring/doctor.py",
    "automation/agent_engine.py",
    "monitoring/health_manager.py",
)


def _tcp_check(host: str, port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _memory_summary() -> str:
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                values[parts[0].rstrip(":")] = int(parts[1]) * 1024
    except (OSError, ValueError):
        return "unavailable"
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    if not total:
        return "unavailable"
    return f"{available / 1_000_000_000:.1f} GB available / {total / 1_000_000_000:.1f} GB"


def collect_checks():
    """Return ordered (status, label, detail) tuples; performs read-only checks."""
    checks = []
    checks.append(("OK", "Python", sys.version.split()[0]))
    checks.append(("OK" if sys.platform.startswith("linux") else "WARN",
                   "Platform", "Android/Termux-compatible Linux" if sys.platform.startswith("linux") else sys.platform))

    missing = [name for name in REQUIRED_FILES if not (ROOT / name).is_file()]
    checks.append(("FAIL" if missing else "OK", "Project files",
                   "missing: " + ", ".join(missing) if missing else f"{len(REQUIRED_FILES)} core files present"))

    packages = ("requests", "prompt_toolkit")
    absent = [name for name in packages if importlib.util.find_spec(name) is None]
    checks.append(("FAIL" if absent else "OK", "Python dependencies",
                   "missing: " + ", ".join(absent) if absent else "requests, prompt_toolkit available"))

    configured_keys = {key for key, value in os.environ.items() if value.strip()}
    # Setup often persists credentials in the project .env without exporting
    # them to the shell. Read key names and non-empty status only; never print
    # or load secret values into the process environment.
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if value.strip().strip('"').strip("'"):
                configured_keys.add(key.strip())
    except OSError:
        pass
    configured = [name for name, keys in PROVIDERS.items()
                  if any(key in configured_keys for key in keys)]
    checks.append(("OK" if configured else "WARN", "AI provider configuration",
                   "configured: " + ", ".join(configured) if configured else "no supported provider key found"))
    # Never display key values, lengths, or environment dumps.

    for name, host, port in SERVICES:
        running = _tcp_check(host, port)
        checks.append(("OK" if running else "WARN", name,
                       f"listening on {host}:{port}" if running else f"not reachable on {host}:{port}"))

    try:
        usage = shutil.disk_usage(str(Path.home()))
        free_gb = usage.free / 1_000_000_000
        status = "FAIL" if free_gb < 0.5 else "WARN" if free_gb < 2 else "OK"
        checks.append((status, "Storage", f"{free_gb:.1f} GB free"))
    except OSError:
        checks.append(("WARN", "Storage", "usage unavailable"))

    checks.append(("OK", "Memory", _memory_summary()))
    api = shutil.which("termux-battery-status")
    checks.append(("OK" if api else "WARN", "Termux:API",
                   "battery command available" if api else "not detected; battery diagnostics unavailable"))
    return checks


def format_report(checks=None):
    """Render checks without leaking credentials; no network/provider requests."""
    checks = collect_checks() if checks is None else checks
    lines = ["JARVIS /doctor — read-only local diagnostics"]
    for status, label, detail in checks:
        lines.append(f"[{status:4}] {label}: {detail}")
    failures = sum(status == "FAIL" for status, _, _ in checks)
    warnings = sum(status == "WARN" for status, _, _ in checks)
    lines.append(f"Summary: {failures} failure(s), {warnings} warning(s).")
    if failures:
        lines.append("Action required: resolve FAIL items before relying on affected features.")
    elif warnings:
        lines.append("Core checks passed; review WARN items for optional or unavailable services.")
    else:
        lines.append("All checked components look healthy.")
    return "\n".join(lines)


def run_doctor():
    return format_report()
