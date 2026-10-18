import os
import shutil
import subprocess

from workers.common.base import Worker


class OpenCodeWorker(Worker):
    name = "opencode"

    def __init__(self):
        self.command = os.getenv("OPENCODE_BIN", "opencode")
        self.model = os.getenv(
            "OPENCODE_MODEL",
            "opencode/mimo-v2.5-free",
        )
        self.timeout = int(
            os.getenv("OPENCODE_TIMEOUT", "900")
        )

    def available(self):
        return shutil.which(self.command) is not None

    def execute(self, task, workspace):
        if not self.available():
            return {
                "success": False,
                "stdout": "",
                "stderr": (
                    f"OpenCode executable not found: "
                    f"{self.command}"
                ),
                "returncode": None,
            }

        task = str(task).strip()
        workspace = os.path.abspath(str(workspace))

        if not task:
            return {
                "success": False,
                "stdout": "",
                "stderr": "OpenCode task is empty.",
                "returncode": None,
            }

        command = [
            self.command,
            "run",
            "-m",
            self.model,
            task,
        ]

        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout,
            )

            return {
                "success": completed.returncode == 0,
                "stdout": completed.stdout or "",
                "stderr": completed.stderr or "",
                "returncode": completed.returncode,
            }

        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""

            if isinstance(stdout, bytes):
                stdout = stdout.decode(
                    "utf-8",
                    errors="replace",
                )

            if isinstance(stderr, bytes):
                stderr = stderr.decode(
                    "utf-8",
                    errors="replace",
                )

            return {
                "success": False,
                "stdout": stdout,
                "stderr": (
                    stderr
                    + f"\nOpenCode timed out after "
                    f"{self.timeout} seconds."
                ),
                "returncode": None,
            }

        except Exception as exc:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "returncode": None,
            }
