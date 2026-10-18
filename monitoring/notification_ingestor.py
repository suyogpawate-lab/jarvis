from jarvis_env import TERMUX_BASH
"""
JARVIS Android notification ingestion layer.
"""

import json
import subprocess


class NotificationIngestor:

    def __init__(self, timeout=15):
        self.timeout = timeout

    def _run(self, command):
        try:
            result = subprocess.run(
                command,
                shell=True,
                executable=TERMUX_BASH,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            return {
                "exit": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }

        except subprocess.TimeoutExpired:
            return {
                "exit": -1,
                "stdout": "",
                "stderr": "Command timed out.",
            }

        except Exception as exc:
            return {
                "exit": -1,
                "stdout": "",
                "stderr": str(exc),
            }

    def raw(self):
        return self._run("termux-notification-list")

    def list(self):
        result = self.raw()

        if result["exit"] != 0:
            return {
                "error": result["stderr"] or "Notification command failed."
            }

        try:
            data = json.loads(result["stdout"] or "[]")
        except json.JSONDecodeError as exc:
            return {
                "error": f"Invalid notification JSON: {exc}",
                "raw": result["stdout"],
            }

        if not isinstance(data, list):
            return {
                "error": "Notification API returned a non-list response."
            }

        return [self._normalize(item) for item in data]

    @staticmethod
    def _normalize(item):
        return {
            "id": item.get("id"),
            "package": item.get("packageName", ""),
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "when": item.get("when", ""),
            "tag": item.get("tag", ""),
            "group": item.get("group", ""),
            "key": item.get("key", ""),
        }

    def summary(self):
        notifications = self.list()

        if isinstance(notifications, dict) and "error" in notifications:
            return notifications

        return {
            "count": len(notifications),
            "notifications": notifications,
        }
