"""Background coding jobs executed by the installed Claude Code CLI.

The CLI is launched in print mode and routed through the local OmniRoute
Anthropic-compatible endpoint. Each job gets its own Git worktree. The worker
never commits, pushes, merges, or deploys changes.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOBS = ROOT / "data" / "coding_jobs"
DEFAULT_WORKTREES = Path.home() / ".jarvis-coding-worktrees"
JOB_ID_RE = re.compile(r"^code-[0-9a-f]{8}$")
ACTIVE = {"STARTING", "RUNNING", "CANCELLING"}
DEFAULT_ALLOWED_TOOLS = (
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(git status *)", "Bash(git diff *)", "Bash(git log *)",
    "Bash(git branch *)", "Bash(git diff --check *)",
    "Bash(python -m pytest *)", "Bash(pytest *)",
    "Bash(python -m unittest *)", "Bash(python -m compileall *)",
    "Bash(node --check *)", "Bash(npm test *)", "Bash(npm run test *)",
)


class CodingAgentManager:
    """Persist, launch, inspect, cancel, and review isolated coding jobs."""

    def __init__(self, repo_root: str | Path | None = None,
                 jobs_dir: str | Path | None = None,
                 worktrees_dir: str | Path | None = None,
                 popen=None):
        self.root = Path(repo_root or ROOT).resolve()
        self.jobs_dir = Path(jobs_dir or DEFAULT_JOBS).resolve()
        self.worktrees_dir = Path(worktrees_dir or DEFAULT_WORKTREES).resolve()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        self._popen = popen or subprocess.Popen
        self._lock = threading.RLock()
        self.command = shlex.split(os.getenv("JARVIS_CODING_AGENT_COMMAND", "claude"))
        self.model = (
            os.getenv("JARVIS_CODING_AGENT_MODEL")
            or os.getenv("OMNIROUTE_CODING_MODEL")
            or os.getenv("OMNIROUTE_COMPLEX_MODEL")
            or "auto/best-reasoning"
        ).strip()
        self.max_turns = max(1, min(int(os.getenv("JARVIS_CODING_AGENT_MAX_TURNS", "20")), 40))
        self.timeout = max(60, min(int(os.getenv("JARVIS_CODING_AGENT_TIMEOUT", "3600")), 14400))
        self.allowed_tools = tuple(
            x.strip() for x in os.getenv("JARVIS_CODING_AGENT_ALLOWED_TOOLS", "").split(",")
            if x.strip()
        ) or DEFAULT_ALLOWED_TOOLS

    @staticmethod
    def is_complex_coding_request(prompt: str) -> bool:
        """Only intercept explicit coding work, not programming questions."""
        text = " ".join(str(prompt or "").split()).lower()
        if len(text) < 18:
            return False
        if re.match(r"^(how|why|what|when|where|who|can i|could i|should i|explain|describe|teach me)\b", text):
            return False
        action = re.search(
            r"\b(fix|debug|implement|refactor|rewrite|build|develop|migrate|"
            r"optimi[sz]e|integrate|add|remove|update|repair|create)\b", text
        )
        target = re.search(
            r"\b(code|coding|program|script|cli|mcp|lora|rlhf|telemetry|workspace|window|ui|repo|repository|codebase|project|"
            r"module|package|tests?|bug|feature|api|python|javascript|typescript|"
            r"android|termux|jarvis|function|class|database|server)\b", text
        )
        complexity = re.search(
            r"\b(repo|repository|codebase|project|module|package|tests?|"
            r"multiple files|architecture|feature|integration|refactor|"
            r"concurrency|performance|memory|regression|end[- ]to[- ]end|"
            r"telemetry|tracking|side quests?|mcp|lora|rlhf|cli|workspace|window|ui)\b", text
        )
        return bool(action and target and complexity)

    def _path(self, job_id: str) -> Path:
        if not JOB_ID_RE.fullmatch(str(job_id or "")):
            raise ValueError("Invalid coding job ID.")
        return self.jobs_dir / (job_id + ".json")

    def _save(self, job: dict[str, Any]) -> None:
        path = self._path(job["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    def _load(self, job_id: str):
        try:
            return json.loads(self._path(job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def _git(self, *args: str, cwd: Path | None = None, timeout: int = 30):
        return subprocess.run(
            ["git", *args], cwd=str(cwd or self.root),
            capture_output=True, text=True, timeout=timeout, check=False,
        )

    def _omniroute_env(self) -> dict[str, str]:
        base = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1").strip().rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        if not base:
            raise RuntimeError("OMNIROUTE_BASE_URL is empty.")
        token = os.getenv("OMNIROUTE_API_KEY", "").strip() or "any-string"
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        env["ANTHROPIC_BASE_URL"] = base
        env["ANTHROPIC_AUTH_TOKEN"] = token
        env["ANTHROPIC_MODEL"] = self.model
        return env

    def _command(self, prompt: str) -> list[str]:
        if not self.command:
            raise RuntimeError("Claude Code command is not configured.")
        if not self.model:
            raise RuntimeError("Set JARVIS_CODING_AGENT_MODEL to an OmniRoute model/combination.")
        return [
            *self.command, "-p", prompt,
            "--output-format", "json",
            "--model", self.model,
            "--permission-mode", "dontAsk",
            "--max-turns", str(self.max_turns),
            "--allowedTools", *self.allowed_tools,
        ]

    def _new_worktree(self, job_id: str) -> tuple[Path, str]:
        if shutil.which("git") is None:
            raise RuntimeError("Git is not installed.")
        check = self._git("rev-parse", "--show-toplevel")
        if check.returncode != 0:
            raise RuntimeError("JARVIS coding jobs require a Git checkout.")
        worktree = self.worktrees_dir / job_id
        branch = "jarvis/coding-" + job_id.removeprefix("code-")
        result = self._git("worktree", "add", "-b", branch, str(worktree), "HEAD")
        if result.returncode != 0:
            detail = " ".join((result.stderr or result.stdout).split())[:400]
            raise RuntimeError("Could not create isolated Git worktree: " + detail)
        return worktree, branch

    @staticmethod
    def _task_prompt(goal: str, job_id: str) -> str:
        return (
            "You are JARVIS's background software-engineering worker. Work only in "
            "the current Git worktree. The user requested:\n\n"
            + goal
            + "\n\nOperating constraints:\n"
            "- Inspect the repository and relevant tests before changing code.\n"
            "- Make the smallest coherent implementation; preserve existing architecture.\n"
            "- Run only the available, relevant tests and report exact commands/results.\n"
            "- Do not read or access .env, credentials, tokens, private keys, WhatsApp auth, "
            "or personal data. Do not inspect parent directories or files outside this worktree.\n"
            "- Do not install dependencies, access the network, run destructive shell commands, "
            "or modify system settings.\n"
            "- Do not commit, push, merge, deploy, publish, or alter Git remotes.\n"
            "- Do not claim a test passed unless its command completed successfully.\n"
            "- If a required action is denied by the restricted tool policy, report it; do not retry "
            "through another mechanism.\n"
            "- Finish with a concise summary, changed-file list, tests and remaining risks.\n"
            "Job ID: " + job_id
        )

    def submit(self, goal: str) -> str:
        goal = str(goal or "").strip()
        if not goal:
            return "[CODE ERROR] A coding goal is required."
        if len(goal) > 12000:
            return "[CODE ERROR] Coding goal exceeds 12,000 characters."
        if not self.command or shutil.which(self.command[0]) is None:
            return (
                "[CODE UNAVAILABLE] Claude Code CLI was not found. Install/configure "
                "the existing claude command and retry; JARVIS will not substitute "
                "a different agent silently."
            )
        try:
            env = self._omniroute_env()
            with self._lock:
                for saved in self.jobs_dir.glob("code-????????.json"):
                    existing = self._load(saved.stem)
                    if existing and existing.get("status") in ACTIVE:
                        self.status(saved.stem)
                        refreshed = self._load(saved.stem)
                        if refreshed and refreshed.get("status") in ACTIVE:
                            return (
                                "[CODE BUSY] One coding job is already active: "
                                + saved.stem + ". Wait for it to finish or cancel it."
                            )
                job_id = "code-" + uuid.uuid4().hex[:8]
                worktree, branch = self._new_worktree(job_id)
        except Exception as exc:
            return "[CODE ERROR] " + str(exc)

        log_path = self.jobs_dir / (job_id + ".log")
        exit_path = self.jobs_dir / (job_id + ".exit")
        job = {
            "id": job_id, "goal": goal, "status": "STARTING",
            "created_at": time.time(), "started_at": None, "finished_at": None,
            "pid": None, "exit_code": None, "model": self.model,
            "backend": "claude-code-cli/omniroute", "branch": branch,
            "worktree": str(worktree), "log": str(log_path), "exit_file": str(exit_path),
            "error": None,
        }
        self._save(job)
        try:
            command = self._command(self._task_prompt(goal, job_id))
            supervisor = (
                "import pathlib,subprocess,sys; "
                "p=pathlib.Path(sys.argv[1]); "
                "r=subprocess.run(sys.argv[2:]); "
                "p.write_text(str(r.returncode), encoding='ascii'); "
                "sys.exit(r.returncode)"
            )
            with log_path.open("w", encoding="utf-8") as log:
                process = self._popen(
                    [sys.executable, "-c", supervisor, str(exit_path), *command],
                    cwd=str(worktree), env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                    text=True,
                )
            job.update(status="RUNNING", pid=process.pid, started_at=time.time())
            self._save(job)
            threading.Thread(
                target=self._wait_job, args=(job_id, process),
                name="jarvis-" + job_id, daemon=True,
            ).start()
            return (
                f"[CODE JOB STARTED] {job_id}\n"
                f"Backend: Claude Code through OmniRoute ({self.model})\n"
                f"Isolated branch: {branch}\n"
                "The interactive Claude Code UI was not opened. "
                f"Check progress with: /code status {job_id}"
            )
        except Exception as exc:
            job.update(status="FAILED", error=f"{type(exc).__name__}: {exc}", finished_at=time.time())
            self._save(job)
            return f"[CODE ERROR] Could not launch Claude Code: {exc}"

    def _wait_job(self, job_id: str, process) -> None:
        try:
            code = process.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=8)
            except Exception:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
            code = 124
        with self._lock:
            job = self._load(job_id)
            if not job:
                return
            job["exit_code"] = code
            job["finished_at"] = time.time()
            job["status"] = "COMPLETED" if code == 0 else ("CANCELLED" if job.get("status") == "CANCELLING" else "FAILED")
            if code == 124:
                job["error"] = "Coding job exceeded its configured time limit."
            self._save(job)

    def status(self, job_id: str) -> str:
        job = self._load(job_id)
        if not job:
            return "[CODE ERROR] Job not found."
        if job.get("status") in ACTIVE:
            marker = Path(job.get("exit_file", ""))
            if marker.is_file():
                try:
                    code = int(marker.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    code = None
                if code is not None:
                    job["exit_code"] = code
                    job["status"] = "COMPLETED" if code == 0 else "FAILED"
                    job["finished_at"] = job.get("finished_at") or time.time()
                    self._save(job)
            elif job.get("pid"):
                try:
                    os.kill(int(job["pid"]), 0)
                except (OSError, ValueError, TypeError):
                    job["status"] = "INTERRUPTED"
                    job["error"] = "Worker exited without a recorded exit code; inspect logs and worktree."
                    job["finished_at"] = time.time()
                    self._save(job)
        elapsed = max(0, int((job.get("finished_at") or time.time()) - (job.get("started_at") or job.get("created_at", time.time()))))
        return (
            f"Job: {job['id']}\nStatus: {job['status']}\nModel: {job.get('model')}\n"
            f"Elapsed: {elapsed}s\nBranch: {job.get('branch')}\n"
            f"Worktree: {job.get('worktree')}\nExit code: {job.get('exit_code')}\n"
            + (f"Error: {job['error']}\n" if job.get("error") else "")
        )

    def list_jobs(self) -> str:
        jobs = []
        for path in self.jobs_dir.glob("code-????????.json"):
            job = self._load(path.stem)
            if job:
                jobs.append(job)
        jobs.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        if not jobs:
            return "[CODE] No coding jobs."
        return "\n".join(
            f"{j['id']}  {j['status']}  {j.get('model', '')}  {j.get('branch', '')}"
            for j in jobs[:20]
        )

    def logs(self, job_id: str, limit: int = 5000) -> str:
        job = self._load(job_id)
        if not job:
            return "[CODE ERROR] Job not found."
        try:
            data = Path(job["log"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "[CODE ERROR] Job log is unavailable."
        return data[-max(500, min(int(limit), 12000)):].strip() or "[CODE] No output yet."

    def cancel(self, job_id: str) -> str:
        job = self._load(job_id)
        if not job:
            return "[CODE ERROR] Job not found."
        if job.get("status") not in ACTIVE:
            return f"[CODE] Job is already {job.get('status')}."
        try:
            os.killpg(int(job["pid"]), signal.SIGTERM)
            job["status"] = "CANCELLING"
            self._save(job)
            return f"[CODE] Cancellation requested for {job_id}."
        except (OSError, ValueError, TypeError) as exc:
            return f"[CODE ERROR] Could not cancel job: {exc}"

    def review(self, job_id: str) -> str:
        job = self._load(job_id)
        if not job:
            return "[CODE ERROR] Job not found."
        worktree = Path(job.get("worktree", ""))
        if not worktree.is_dir():
            return "[CODE ERROR] Coding worktree no longer exists."
        status = self._git("status", "--short", cwd=worktree)
        diff = self._git("diff", "HEAD", "--stat", cwd=worktree)
        return (
            f"Job: {job_id} ({job.get('status')})\n"
            f"Branch: {job.get('branch')}\n"
            "Git status:\n" + (status.stdout.strip() or "(clean)") +
            "\nDiff summary:\n" + (diff.stdout.strip() or "(no unstaged diff)")
        )

    def handle(self, command: str) -> str:
        text = str(command or "").strip()
        match = re.match(r"^/code(?:\s+(.*))?$", text, re.I | re.S)
        if not match:
            return "[CODE ERROR] Invalid command."
        args = (match.group(1) or "").strip()
        if not args or args.lower() in {"help", "?"}:
            return (
                "/code start <complex coding goal>\n"
                "/code status <job-id>\n/code list\n/code logs <job-id>\n"
                "/code review <job-id>\n/code cancel <job-id>\n"
                "Coding jobs use Claude Code in non-interactive mode through OmniRoute, "
                "inside a separate Git worktree. They never auto-merge."
            )
        if args.lower() == "list":
            return self.list_jobs()
        action, _, value = args.partition(" ")
        action = action.lower()
        value = value.strip()
        if action == "start":
            return self.submit(value)
        if action in {"status", "logs", "review", "cancel"} and value:
            job_id = value.split()[0]
            if action == "status":
                return self.status(job_id)
            if action == "logs":
                return self.logs(job_id)
            if action == "review":
                return self.review(job_id)
            return self.cancel(job_id)
        return "[CODE ERROR] Use /code help for supported commands."
