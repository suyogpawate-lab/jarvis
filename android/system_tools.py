from jarvis_env import TERMUX_BASH
"""
JARVIS read-only system inspection.
"""

import os
import platform
import shutil
import subprocess


class SystemTools:

    def _run(self, command, timeout=10):
        try:
            p = subprocess.run(
                command,
                shell=True,
                executable=TERMUX_BASH,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return {
                "exit": p.returncode,
                "stdout": p.stdout.strip(),
                "stderr": p.stderr.strip(),
            }

        except Exception as exc:
            return {
                "exit": -1,
                "stdout": "",
                "stderr": str(exc),
            }

    def overview(self):
        data = []

        data.append(
            f"OS: {platform.system()} "
            f"{platform.release()}"
        )

        data.append(
            f"Architecture: {platform.machine()}"
        )

        data.append(
            f"Python: {platform.python_version()}"
        )

        data.append(
            f"CPU count: {os.cpu_count()}"
        )

        for command in (
            "uptime",
            "free -h",
            "df -h",
            "ps -A",
        ):
            result = self._run(command)

            if result["stdout"]:
                data.append(
                    f"$ {command}\n"
                    f"{result['stdout']}"
                )

        return "\n\n".join(data)

    def battery(self):
        return self._run(
            "termux-battery-status"
        )

    def wifi(self):
        return self._run(
            "termux-wifi-connectioninfo"
        )

    def processes(self, limit=40):
        result = self._run("ps -A")

        if result["exit"] != 0:
            return result

        lines = result["stdout"].splitlines()

        if len(lines) > limit + 1:
            lines = lines[:limit + 1]

        result["stdout"] = "\n".join(lines)

        return result

    def storage(self):
        return self._run("df -h")

    def memory(self):
        return self._run("free -h")

    def available(self, command):
        return shutil.which(command) is not None
