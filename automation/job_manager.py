from jarvis_env import TERMUX_BASH
from android.command_guard import check as guard_check
"""
JARVIS background job manager.
"""

import json
import os
import signal
import subprocess
import shlex
import time
import uuid


class JobManager:

    def __init__(self, base_dir="data/jobs"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, job_id):
        return os.path.join(
            self.base_dir,
            f"{job_id}.json",
        )

    def _save(self, job):
        with open(
            self._path(job["id"]),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                job,
                f,
                indent=2,
            )

    def _load(self, job_id):
        path = self._path(job_id)

        if not os.path.exists(path):
            return None

        with open(
            path,
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    def _refresh(self, job):
        pid = job.get("pid")

        if not pid:
            return job

        try:
            result = subprocess.run(
                [
                    "ps",
                    "-p",
                    str(pid),
                    "-o",
                    "stat=",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )

            state = result.stdout.strip()

        except Exception:
            state = ""

        # A zombie has exited but may still have a PID entry.
        running = bool(state) and not state.startswith("Z")

        if job["status"] == "RUNNING" and not running:
            exit_code = None
            try:
                with open(job["exit_code_file"], "r", encoding="ascii") as stream:
                    exit_code = int(stream.read().strip())
            except (OSError, ValueError, TypeError):
                # Missing status must never be interpreted as successful.
                pass
            job["exit_code"] = exit_code
            job["status"] = "DONE" if exit_code == 0 else "FAILED"
            if exit_code is None:
                job["error"] = "Process ended without a recorded exit status."
            job["finished_at"] = time.time()
            self._save(job)

        return job

    def start(self, command, cwd=None):
        command = str(command).strip()

        if not command:
            return {
                "error": "Empty command."
            }

        verdict = guard_check(command, kind="job")
        if verdict:
            return {"error": verdict}

        job_id = (
            "job-"
            + uuid.uuid4().hex[:8]
        )

        stdout_file = os.path.abspath(
            os.path.join(
                self.base_dir,
                f"{job_id}.stdout",
            )
        )

        stderr_file = os.path.abspath(
            os.path.join(
                self.base_dir,
                f"{job_id}.stderr",
            )
        )
        exit_code_file = os.path.abspath(os.path.join(self.base_dir, f"{job_id}.exit"))
        wrapped_command = (
            f"({command})\n"
            f"__jarvis_status=$?\n"
            f"printf '%s' \"$__jarvis_status\" > {shlex.quote(exit_code_file)}\n"
            f"exit \"$__jarvis_status\""
        )

        try:
            stdout = open(
                stdout_file,
                "w",
                encoding="utf-8",
            )

            stderr = open(
                stderr_file,
                "w",
                encoding="utf-8",
            )

            process = subprocess.Popen(
                wrapped_command,
                shell=True,
                executable=TERMUX_BASH,
                cwd=cwd or os.getcwd(),
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                text=True,
            )

            stdout.close()
            stderr.close()

        except Exception as exc:
            return {
                "error": str(exc)
            }

        job = {
            "id": job_id,
            "command": command,
            "pid": process.pid,
            "cwd": cwd or os.getcwd(),
            "status": "RUNNING",
            "started_at": time.time(),
            "finished_at": None,
            "stdout_file": stdout_file,
            "stderr_file": stderr_file,
            "exit_code_file": exit_code_file,
            "exit_code": None,
        }

        self._save(job)

        return job

    def status(self, job_id):
        job = self._load(job_id)

        if not job:
            return {
                "error": f"Unknown job: {job_id}"
            }

        return self._refresh(job)

    def list(self):
        jobs = []

        for filename in os.listdir(self.base_dir):
            if not filename.endswith(".json"):
                continue

            job_id = filename[:-5]

            job = self._load(job_id)

            if job:
                jobs.append(
                    self._refresh(job)
                )

        jobs.sort(
            key=lambda x: x.get("started_at", 0),
            reverse=True,
        )

        return jobs

    def output(self, job_id, max_bytes=12000):
        job = self._load(job_id)

        if not job:
            return {
                "error": f"Unknown job: {job_id}"
            }

        job = self._refresh(job)

        def read_file(path):
            if not os.path.exists(path):
                return ""

            with open(
                path,
                "r",
                encoding="utf-8",
                errors="replace",
            ) as f:
                data = f.read()

            return data[-max_bytes:]

        return {
            "id": job["id"],
            "status": job["status"],
            "stdout": read_file(
                job["stdout_file"]
            ),
            "stderr": read_file(
                job["stderr_file"]
            ),
        }

    def stop(self, job_id):
        job = self._load(job_id)

        if not job:
            return {
                "error": f"Unknown job: {job_id}"
            }

        job = self._refresh(job)

        if job["status"] != "RUNNING":
            return job

        pid = int(job["pid"])

        try:
            os.killpg(
                pid,
                signal.SIGTERM,
            )
        except ProcessLookupError:
            job["status"] = "STOPPED"
            job["finished_at"] = time.time()
            self._save(job)
            return job
        except PermissionError as exc:
            return {
                "error": str(exc),
                "job": job,
            }

        # Verify termination.
        for _ in range(10):
            time.sleep(0.2)

            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                job["status"] = "STOPPED"
                job["finished_at"] = time.time()
                self._save(job)
                return job
            except Exception:
                break

        job["status"] = "STOPPED"
        job["finished_at"] = time.time()
        self._save(job)

        return job
