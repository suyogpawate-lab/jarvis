"""
JARVIS persistent automation scheduler.

The scheduler owns timing only.
Actual work is delegated back to the existing JARVIS dispatcher.

Timezone-aware version.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, time as datetime_time, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _resolve_timezone(requested=None):
    """Resolve an IANA timezone, preferring explicit JARVIS configuration."""
    candidates = []
    if requested:
        candidates.append(str(requested).strip())
    else:
        for value in (os.environ.get("JARVIS_TIMEZONE"), os.environ.get("TZ")):
            if value:
                value = value.strip()
                if value.startswith(":"):
                    value = value[1:]
                if value and value not in candidates:
                    candidates.append(value)

    for candidate in candidates:
        marker = "/zoneinfo/"
        if marker in candidate:
            candidate = candidate.split(marker, 1)[1]
        try:
            return candidate, ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            if requested:
                raise ValueError(
                    f"Invalid IANA timezone {requested!r}. "
                    "Use a name such as Europe/London or America/New_York."
                )

    # Android exposes the device's configured IANA timezone here.
    try:
        result = subprocess.run(
            ["/system/bin/getprop", "persist.sys.timezone"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        name = result.stdout.strip()
        if name:
            return name, ZoneInfo(name)
    except (OSError, subprocess.SubprocessError, ZoneInfoNotFoundError, ValueError):
        pass

    # Unix-like systems commonly link /etc/localtime to a zoneinfo file.
    try:
        localtime_path = os.path.realpath("/etc/localtime")
        marker = "/zoneinfo/"
        if marker in localtime_path:
            name = localtime_path.split(marker, 1)[1]
            return name, ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        pass

    # Last resort: use the platform's local offset, never assume a country.
    # Set JARVIS_TIMEZONE to an IANA name for DST-safe behaviour when the
    # platform does not expose its timezone identifier.
    local_tz = datetime.now().astimezone().tzinfo or datetime_timezone.utc
    return "LOCAL", local_tz


class AutomationScheduler:

    def __init__(
        self,
        callback,
        base_dir="data/automations",
        timezone=None,
    ):
        self.callback = callback
        self.timezone_name, self.timezone = _resolve_timezone(timezone)

        self.base_dir = os.path.join(os.path.dirname(__file__), "..", "data", "automations")
        os.makedirs(self.base_dir, exist_ok=True)

        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        self._thread = threading.Thread(
            target=self._loop,
            name="jarvis-automation-scheduler",
            daemon=True,
        )

        self._thread.start()

    # ----------------------------------------------------------
    # STORAGE
    # ----------------------------------------------------------

    def _path(self, automation_id):
        return os.path.join(
            self.base_dir,
            f"{automation_id}.json",
        )

    def _save(self, automation):
        with open(
            self._path(automation["id"]),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                automation,
                f,
                indent=2,
                ensure_ascii=False,
            )

    def _load(self, automation_id):
        path = self._path(automation_id)

        if not os.path.exists(path):
            return None

        try:
            with open(
                path,
                "r",
                encoding="utf-8",
            ) as f:
                return json.load(f)
        except Exception:
            return None

    def list(self):
        result = []

        with self._lock:
            for filename in os.listdir(self.base_dir):
                if not filename.endswith(".json"):
                    continue

                automation = self._load(
                    filename[:-5]
                )

                if automation:
                    result.append(automation)

        result.sort(
            key=lambda x: (
                x.get("next_run")
                if x.get("next_run") is not None
                else float("inf")
            )
        )

        return result

    # ----------------------------------------------------------
    # CREATE
    # ----------------------------------------------------------

    def schedule(
        self,
        command,
        run_at,
        repeat_seconds=None,
        description=None,
        repeat_mode=None,
        repeat_at=None,
    ):
        automation_id = (
            "auto-" + uuid.uuid4().hex[:8]
        )

        automation = {
            "id": automation_id,
            "command": str(command).strip(),
            "description": (
                description
                or str(command).strip()
            ),
            "run_at": float(run_at),
            "next_run": float(run_at),
            "repeat_seconds": (
                float(repeat_seconds)
                if repeat_seconds
                else None
            ),
            "repeat_mode": repeat_mode,
            "repeat_at": repeat_at,
            "status": "SCHEDULED",
            "created_at": time.time(),
            "last_run": None,
            "last_result": None,
            "run_count": 0,
            "timezone": self.timezone_name,
        }

        with self._lock:
            self._save(automation)

        return automation

    def timer(
        self,
        command,
        seconds,
        description=None,
    ):
        return self.schedule(
            command=command,
            run_at=time.time() + float(seconds),
            description=description,
        )

    def daily(
        self,
        command,
        hour,
        minute=0,
        description=None,
    ):
        now = datetime.now(self.timezone)

        run_at = now.replace(
            hour=int(hour),
            minute=int(minute),
            second=0,
            microsecond=0,
        )

        if run_at <= now:
            run_at += timedelta(days=1)

        return self.schedule(
            command=command,
            run_at=run_at.timestamp(),
            description=description,
            repeat_mode="daily",
            repeat_at=f"{int(hour):02d}:{int(minute):02d}",
        )

    def _next_repeat_time(self, automation, now=None):
        """Compute an interval or local-calendar recurrence."""
        now = time.time() if now is None else float(now)
        previous = automation.get("next_run")

        if automation.get("repeat_mode") == "daily" and previous is not None:
            scheduled = datetime.fromtimestamp(float(previous), self.timezone)
            hour, minute = map(
                int, str(automation.get("repeat_at", "00:00")).split(":", 1)
            )
            local_date = scheduled.date() + timedelta(days=1)

            # Use calendar days plus the saved wall-clock time, not 86400
            # seconds, so recurring tasks do not drift at DST boundaries.
            while True:
                local_candidate = datetime.combine(
                    local_date,
                    datetime_time(hour=hour, minute=minute),
                    tzinfo=self.timezone,
                )
                next_run = local_candidate.timestamp()
                if next_run > now:
                    return next_run
                local_date += timedelta(days=1)

        repeat_seconds = automation.get("repeat_seconds")
        if repeat_seconds:
            next_run = (
                float(previous) + float(repeat_seconds)
                if previous is not None
                else now + float(repeat_seconds)
            )
            while next_run <= now:
                next_run += float(repeat_seconds)
            return next_run

        return None

    # ----------------------------------------------------------
    # CONTROL
    # ----------------------------------------------------------

    def cancel(self, automation_id):
        with self._lock:
            automation = self._load(automation_id)

            if not automation:
                return {
                    "error": (
                        f"Unknown automation: "
                        f"{automation_id}"
                    )
                }

            automation["status"] = "CANCELLED"
            automation["cancelled_at"] = time.time()

            self._save(automation)

            return automation

    def get(self, automation_id):
        return self._load(automation_id)

    # ----------------------------------------------------------
    # EXECUTION
    # ----------------------------------------------------------

    def _execute(self, automation):
        command = automation.get(
            "command",
            "",
        ).strip()

        if not command:
            return

        try:
            result = self.callback(command)

            automation["last_result"] = str(result)
            automation["last_run"] = time.time()
            automation["run_count"] = (
                automation.get("run_count", 0) + 1
            )

            if (
                automation.get("repeat_seconds")
                or automation.get("repeat_mode") == "daily"
            ):
                automation["next_run"] = self._next_repeat_time(automation)
                automation["status"] = "SCHEDULED"

            else:
                automation["next_run"] = None
                automation["status"] = "DONE"

        except Exception as exc:
            automation["last_result"] = (
                f"[ERROR] {exc}"
            )
            automation["last_run"] = time.time()

            if (
                automation.get("repeat_seconds")
                or automation.get("repeat_mode") == "daily"
            ):
                automation["next_run"] = self._next_repeat_time(automation)
                automation["status"] = "SCHEDULED"
            else:
                automation["next_run"] = None
                automation["status"] = "FAILED"

        with self._lock:
            self._save(automation)

    # ----------------------------------------------------------
    # LOOP
    # ----------------------------------------------------------

    def _loop(self):
        while not self._stop_event.wait(1.0):
            now = time.time()
            due = []

            with self._lock:
                for filename in os.listdir(
                    self.base_dir
                ):
                    if not filename.endswith(".json"):
                        continue

                    automation = self._load(
                        filename[:-5]
                    )

                    if not automation:
                        continue

                    if (
                        automation.get("status")
                        != "SCHEDULED"
                    ):
                        continue

                    next_run = automation.get(
                        "next_run"
                    )

                    if next_run is None:
                        continue

                    if float(next_run) <= now:
                        due.append(automation)

            for automation in due:
                self._execute(automation)

    def shutdown(self):
        self._stop_event.set()

        if self._thread.is_alive():
            self._thread.join(
                timeout=2
            )
