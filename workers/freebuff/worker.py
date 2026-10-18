"""
JARVIS -> Freebuff bridge.

Runs the Linux ARM64 Freebuff binary through Debian/proot-distro.
"""

import os
import shutil
import subprocess

from workers.common.base import Worker


class FreebuffWorker(Worker):

    name = "freebuff"

    TERMUX_HOME = "/data/data/com.termux/files/home"
    BINARY = (
        "/data/data/com.termux/files/home/"
        "freebuff-linux-test/freebuff"
    )

    def available(self):
        return (
            shutil.which("proot-distro") is not None
            and os.path.isfile(self.BINARY)
        )

    def execute(self, task, workspace):

        if not self.available():
            raise RuntimeError(
                "Freebuff bridge unavailable"
            )

        workspace = os.path.abspath(workspace)

        if not os.path.isdir(workspace):
            raise RuntimeError(
                f"Workspace does not exist: {workspace}"
            )

        # Convert Termux path to the same path visible
        # from the Debian proot environment.
        command = [
            "proot-distro",
            "login",
            "debian",
            "--",
            "bash",
            "-lc",
            (
                "cd \"$1\" && "
                "exec \"$2\""
            ),
            "jarvis-freebuff",
            workspace,
            self.BINARY,
        ]

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        try:
            process.stdin.write(task + "\n")
            process.stdin.flush()
            process.stdin.close()

            output = process.stdout.read()
            returncode = process.wait(timeout=1800)

        except subprocess.TimeoutExpired:
            process.kill()
            raise RuntimeError(
                "Freebuff execution timed out"
            )

        return {
            "worker": self.name,
            "returncode": returncode,
            "stdout": output,
            "success": returncode == 0,
        }
