#!/usr/bin/env python3
"""Background health monitor that raises alerts (see alerts.py).

Checks: battery level + temperature (needs Termux:API), free storage, and whether
the OmniRoute "brain" endpoint is reachable. Alerts are edge-triggered: you hear
about a problem once when it starts (and again if it gets worse), plus an info
alert when it clears - no nagging every poll.
"""
import os
import json
import time
import shutil
import socket
import threading
import subprocess
from urllib.parse import urlparse

from monitoring import alerts

BATTERY_WARN = 20          # percent, while discharging
BATTERY_URGENT = 10
TEMP_WARN = 42.0           # deg C
TEMP_URGENT = 45.0
STORAGE_WARN_GB = 2.0
STORAGE_URGENT_GB = 0.5
POLL_SECONDS = 45


class AlertMonitor:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self._level = {}            # check name -> last level raised (0 ok, 1 warn, 2 urgent)
        self._brain_fail = 0
        self._termux_api = shutil.which("termux-battery-status") is not None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="alert-monitor")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------
    def _edge(self, name, level, warn_text, urgent_text, clear_text):
        """Raise only when the level changes. level: 0 ok, 1 warn, 2 urgent."""
        prev = self._level.get(name, 0)
        if level == prev:
            return
        self._level[name] = level
        if level == 2:
            alerts.post(urgent_text, "urgent", name, speak=True, dedup=0)
        elif level == 1:
            alerts.post(warn_text, "warn", name, dedup=0)
        elif prev:
            alerts.post(clear_text, "info", name, dedup=0)

    def _check_battery(self):
        if not self._termux_api:
            return
        try:
            r = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=8)
            data = json.loads(r.stdout)
        except Exception:
            return
        pct = data.get("percentage", data.get("level"))
        status = str(data.get("status") or "").strip().upper()
        plugged = data.get("plugged")
        if isinstance(plugged, bool):
            is_plugged = plugged
        elif isinstance(plugged, (int, float)):
            is_plugged = plugged != 0
        else:
            is_plugged = str(plugged or "").strip().upper() in {
                "AC", "USB", "WIRELESS", "PLUGGED", "PLUGGED_IN", "TRUE", "1"
            }
        charging = status in ("CHARGING", "FULL") or is_plugged
        if isinstance(pct, (int, float)):
            lvl = 0
            if not charging:
                lvl = 2 if pct <= BATTERY_URGENT else 1 if pct <= BATTERY_WARN else 0
            self._edge("battery", lvl,
                       f"Battery at {int(pct)} percent. Consider charging.",
                       f"Battery critically low at {int(pct)} percent.",
                       "Battery level is back to normal.")
        temp = data.get("temperature")
        if isinstance(temp, (int, float)):
            lvl = 2 if temp >= TEMP_URGENT else 1 if temp >= TEMP_WARN else 0
            self._edge("temperature", lvl,
                       f"Device is running warm at {temp:.0f} degrees.",
                       f"Device is overheating at {temp:.0f} degrees.",
                       "Device temperature is back to normal.")

    def _check_storage(self):
        try:
            free_gb = shutil.disk_usage(os.path.expanduser("~")).free / 1e9
        except Exception:
            return
        lvl = 2 if free_gb <= STORAGE_URGENT_GB else 1 if free_gb <= STORAGE_WARN_GB else 0
        self._edge("storage", lvl,
                   f"Storage is getting low: {free_gb:.1f} gigabytes free.",
                   f"Storage is nearly full: {free_gb:.1f} gigabytes free.",
                   "Storage space is back to normal.")

    def _check_brain(self):
        base = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
        u = urlparse(base)
        host = u.hostname or "127.0.0.1"
        port = u.port or (443 if u.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=3):
                ok = True
        except OSError:
            ok = False
        self._brain_fail = 0 if ok else self._brain_fail + 1
        # two consecutive failures before crying wolf
        lvl = 2 if self._brain_fail >= 2 else 0
        self._edge("brain", lvl,
                   "", "My reasoning backend is unreachable. Replies will fail until OmniRoute is back.",
                   "My reasoning backend is back online.")

    def _run(self):
        time.sleep(5)
        while not self._stop.is_set():
            for check in (self._check_brain, self._check_battery, self._check_storage):
                try:
                    check()
                except Exception:
                    pass
            self._stop.wait(POLL_SECONDS)
