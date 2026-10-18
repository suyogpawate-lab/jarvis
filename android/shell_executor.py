from jarvis_env import TERMUX_BASH
"""
JARVIS shell execution layer.
"""

import os
import subprocess


class ShellExecutor:

    def __init__(self, timeout=120):
        self.timeout = timeout

    def execute(self, command, cwd=None):

        command = str(command).strip()

        if not command:
            return "[ERROR] Empty shell command."

        try:
            process = subprocess.run(
                command,
                shell=True,
                executable=TERMUX_BASH,
                cwd=cwd or os.getcwd(),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            stdout = process.stdout.strip()
            stderr = process.stderr.strip()

            result = [
                f"[EXEC] {command}",
                f"[EXIT] {process.returncode}",
            ]

            if stdout:
                result.append(
                    f"[STDOUT]\n{stdout}"
                )

            if stderr:
                result.append(
                    f"[STDERR]\n{stderr}"
                )

            return "\n".join(result)

        except subprocess.TimeoutExpired:
            return (
                f"[ERROR] Command timed out after "
                f"{self.timeout}s: {command}"
            )

        except Exception as exc:
            return (
                f"[ERROR] Shell execution failed: {exc}"
            )
