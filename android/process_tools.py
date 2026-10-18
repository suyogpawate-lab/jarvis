from jarvis_env import TERMUX_BASH
"""
JARVIS process control and verification layer.
"""

import os
import signal
import subprocess
import time


class ProcessTools:

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

    def list(self, limit=40):
        result = self._run("ps -A")

        if result["exit"] != 0:
            return result

        lines = result["stdout"].splitlines()

        if len(lines) > limit + 1:
            lines = lines[:limit + 1]

        result["stdout"] = "\n".join(lines)
        return result

    def find(self, name):
        name = str(name).strip()

        if not name:
            return {
                "exit": 1,
                "stdout": "",
                "stderr": "Process name missing.",
            }

        # Use grep only for discovery; no process is modified.
        safe_name = subprocess.list2cmdline([name])

        return self._run(
            f"ps -A | grep -i -- {safe_name} | grep -v grep"
        )

    def is_running(self, name):
        result = self.find(name)

        return {
            "running": (
                result["exit"] == 0
                and bool(result["stdout"])
            ),
            "processes": result["stdout"],
            "error": result["stderr"],
        }

    def inspect(self, pid):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return {
                "exit": 1,
                "stdout": "",
                "stderr": "Invalid PID.",
            }

        if pid <= 0:
            return {
                "exit": 1,
                "stdout": "",
                "stderr": "Invalid PID.",
            }

        return self._run(
            f"ps -p {pid} "
            f"-o pid,ppid,user,%cpu,%mem,etime,args"
        )

    def stop(self, pid, force=False, verify=True):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return "[ERROR] Invalid PID."

        if pid <= 1:
            return "[ERROR] Refusing to stop protected PID."

        sig = signal.SIGKILL if force else signal.SIGTERM
        signal_name = "SIGKILL" if force else "SIGTERM"

        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return f"[ERROR] PID {pid} does not exist."
        except PermissionError:
            return f"[ERROR] Permission denied for PID {pid}."
        except Exception as exc:
            return f"[ERROR] Failed to stop PID {pid}: {exc}"

        if not verify:
            return f"[OK] Sent {signal_name} to PID {pid}."

        # Give the process a short opportunity to exit.
        for _ in range(10):
            time.sleep(0.2)

            result = self.inspect(pid)

            if result["exit"] != 0 or not result["stdout"]:
                return (
                    f"[OK] Sent {signal_name} to PID {pid}.\n"
                    f"[VERIFY] Process is no longer present."
                )

        return (
            f"[WARN] Sent {signal_name} to PID {pid}, "
            f"but verification still shows the process."
        )

    def verify_pid(self, pid):
        result = self.inspect(pid)

        running = (
            result["exit"] == 0
            and bool(result["stdout"])
        )

        return {
            "running": running,
            "process": result["stdout"],
            "error": result["stderr"],
        }
