"""
JARVIS persistent automation scheduler.

The scheduler owns timing only.
Actual work is delegated back to the existing JARVIS dispatcher.

Timezone-aware version.
"""

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class AutomationScheduler:

    def __init__(
        self,
        callback,
        base_dir="data/automations",
        timezone="Asia/Kolkata",
    ):
        self.callback = callback
        self.timezone_name = str(timezone)

        try:
            self.timezone = ZoneInfo(self.timezone_name)
        except Exception:
            self.timezone_name = "Asia/Kolkata"
            self.timezone = ZoneInfo("Asia/Kolkata")

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
            repeat_seconds=86400,
            description=description,
        )

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

            repeat_seconds = automation.get(
                "repeat_seconds"
            )

            if repeat_seconds:
                # Keep the recurring schedule tied to the
                # previous scheduled time instead of execution
                # time, preventing cumulative drift.
                previous = automation.get(
                    "next_run"
                )

                if previous:
                    next_run = (
                        float(previous)
                        + float(repeat_seconds)
                    )

                    while next_run <= time.time():
                        next_run += float(
                            repeat_seconds
                        )
                else:
                    next_run = (
                        time.time()
                        + float(repeat_seconds)
                    )

                automation["next_run"] = next_run
                automation["status"] = "SCHEDULED"

            else:
                automation["next_run"] = None
                automation["status"] = "DONE"

        except Exception as exc:
            automation["last_result"] = (
                f"[ERROR] {exc}"
            )
            automation["last_run"] = time.time()

            repeat_seconds = automation.get(
                "repeat_seconds"
            )

            if repeat_seconds:
                automation["next_run"] = (
                    time.time()
                    + float(repeat_seconds)
                )
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
