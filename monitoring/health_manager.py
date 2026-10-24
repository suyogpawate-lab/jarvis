"""Low-overhead proactive device/service health checks for JARVIS.

The monitor is read-only: it reports pressure and actionable suggestions but
never kills processes, restarts services, or changes device settings itself.
"""
from __future__ import annotations

import os
import shutil
import socket
import threading
import time
from pathlib import Path

from monitoring.system_telemetry import get_telemetry


DEFAULT_INTERVAL = 300
SERVICES = (
    ("OmniRoute", "127.0.0.1", 20128),
    ("Knowledge Hub", "127.0.0.1", 8766),
    ("WhatsApp bridge", "127.0.0.1", 23841),
    ("Ollama", "127.0.0.1", 11434),
)


class HealthManager:
    def __init__(self, interval=None, on_warning=None):
        raw = interval if interval is not None else os.getenv("JARVIS_HEALTH_INTERVAL", DEFAULT_INTERVAL)
        try:
            self.interval = max(60, min(int(raw), 3600))
        except (TypeError, ValueError):
            self.interval = DEFAULT_INTERVAL
        self.on_warning = on_warning or self._default_warning
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last_warnings = set()

    @staticmethod
    def _default_warning(message):
        print(f"[JARVIS HEALTH] {message}", flush=True)

    @staticmethod
    def _reachable(host, port, timeout=0.35):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def collect(self):
        telemetry = get_telemetry()
        memory = telemetry.get("memory", {})
        warnings = []
        suggestions = []
        cpu = float(telemetry.get("cpu", {}).get("percent", 0) or 0)
        ram_percent = float(memory.get("percent", 0) or 0)
        swap_percent = float(memory.get("swap_percent", 0) or 0)
        ram_available = int(memory.get("available", 0) or 0)

        if ram_percent >= 92 or (ram_available and ram_available < 250 * 1024 * 1024):
            warnings.append("RAM pressure is critical")
            suggestions.append("Close unused apps or stop a confirmed runaway process; inspect before terminating anything.")
        elif ram_percent >= 85:
            warnings.append("RAM usage is high")
            suggestions.append("Avoid starting another local model or memory-heavy build until usage drops.")
        if swap_percent >= 85:
            warnings.append("Swap usage is high")
            suggestions.append("Prefer lightweight tasks and check which processes are consuming memory.")
        if cpu >= 90:
            warnings.append("CPU usage is high")
            suggestions.append("Check active jobs with /bg list and inspect top processes before stopping work.")

        try:
            usage = shutil.disk_usage(str(Path.home()))
            free = usage.free
            if free < 512 * 1024 * 1024:
                warnings.append("Free storage is critically low")
                suggestions.append("Inspect cache and project artifacts before deleting anything.")
            elif free < 2 * 1024 * 1024 * 1024:
                warnings.append("Free storage is low")
                suggestions.append("Review large downloads and caches; do not delete project or personal data blindly.")
        except OSError:
            free = None

        services = {}
        for name, host, port in SERVICES:
            # Ollama is optional; only flag the primary integrations by default.
            ok = self._reachable(host, port)
            services[name] = ok
            if not ok and name != "Ollama":
                warnings.append(f"{name} is not reachable on port {port}")
                suggestions.append(f"Run /doctor and inspect the {name} service logs before restarting it.")

        return {
            "timestamp": time.time(),
            "cpu_percent": cpu,
            "ram_percent": ram_percent,
            "ram_available": ram_available,
            "swap_percent": swap_percent,
            "free_storage": free,
            "services": services,
            "warnings": warnings,
            "suggestions": list(dict.fromkeys(suggestions)),
        }

    def report(self):
        data = self.collect()
        lines = ["JARVIS proactive health report (read-only)"]
        lines.append(f"CPU: {data['cpu_percent']:.1f}%")
        lines.append(f"RAM: {data['ram_percent']:.1f}% used; {data['ram_available'] / (1024 ** 2):.0f} MiB available")
        lines.append(f"Swap: {data['swap_percent']:.1f}% used")
        free = data.get("free_storage")
        lines.append("Storage: unavailable" if free is None else f"Storage: {free / (1024 ** 3):.2f} GiB free")
        lines.append("Services:")
        lines.extend(f"  {'OK' if ok else 'DOWN'} — {name}" for name, ok in data["services"].items())
        if data["warnings"]:
            lines.append("Warnings:")
            lines.extend(f"  ! {item}" for item in data["warnings"])
        else:
            lines.append("No threshold warnings detected.")
        if data["suggestions"]:
            lines.append("Suggested next steps:")
            lines.extend(f"  - {item}" for item in data["suggestions"])
        lines.append("No services were restarted and no files or processes were changed.")
        return "\n".join(lines)

    def poll_once(self):
        data = self.collect()
        current = set(data["warnings"])
        with self._lock:
            newly_seen = current - self._last_warnings
            self._last_warnings = current
        for warning in sorted(newly_seen):
            try:
                self.on_warning(warning)
            except Exception:
                pass
        return data

    def start(self):
        """Start one daemon monitor; the first check occurs after one interval."""
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-health-monitor", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.poll_once()
            except Exception as exc:
                try:
                    self.on_warning(f"Health check failed: {type(exc).__name__}: {exc}")
                except Exception:
                    pass
