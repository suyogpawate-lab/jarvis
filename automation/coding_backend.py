"""Configurable external coding-agent adapter for JARVIS.

The coding agent is deliberately separate from JARVIS's conversational LLM.
It invokes a locally installed CLI with an argv list (never shell=True), in a
configured workspace, and leaves provider authentication to that CLI.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_PROMPT_CHARS = 12000
MAX_OUTPUT_CHARS = 16000
DEFAULT_TIMEOUT = 1800

PRESETS = {
    "claude": "claude -p {prompt}",
    "claude-code": "claude -p {prompt}",
    "codex": "codex exec {prompt}",
}


class PersistentCodingSession:
    """Manages a long-lived persistent coding CLI process using stream-json protocol."""

    def __init__(self, argv, workspace, timeout, popen_factory=None):
        self.argv = argv
        self.workspace = workspace
        self.timeout = timeout
        self.popen_factory = subprocess.Popen if popen_factory is None else popen_factory
        self.process = None
        self.lock = threading.Lock()
        self.reader_thread = None
        self.running = False
        self.current_output = []
        self.task_event = threading.Event()
        self.stdout_file = None
        self.stderr_file = None

    def start(self):
        with self.lock:
            if self.running and self.process and self.process.poll() is None:
                return True
            try:
                # Use stream-json mode for persistent interactive protocol
                base_argv = [arg for arg in self.argv if arg not in {"-p", "--print"}]
                # Ensure stream-json format flags are present if claude
                if "claude" in base_argv[0] or base_argv[0].endswith("node"):
                    if "--output-format" not in base_argv:
                        base_argv.extend(["--output-format", "stream-json", "--input-format", "stream-json"])

                self.stdout_file = tempfile.TemporaryFile()
                self.stderr_file = tempfile.TemporaryFile()

                self.process = self.popen_factory(
                    base_argv,
                    cwd=str(self.workspace),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=self.stderr_file,
                )
                self.running = True
                self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
                self.reader_thread.start()
                return True
            except Exception as exc:
                self.running = False
                return False

    def _reader_loop(self):
        buffer = []
        while self.running and self.process and self.process.poll() is None:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                text_line = line.decode("utf-8", errors="replace").strip()
                if not text_line:
                    continue
                try:
                    data = json.loads(text_line)
                    msg_type = data.get("type")
                    if msg_type == "assistant":
                        msg = data.get("message", {})
                        for content_block in msg.get("content", []):
                            if content_block.get("type") == "text":
                                self.current_output.append(content_block.get("text", ""))
                    elif msg_type == "result":
                        res = data.get("result", "")
                        if res:
                            self.current_output.append(str(res))
                        self.task_event.set()
                    elif "text" in data:
                        self.current_output.append(str(data["text"]))
                except json.JSONDecodeError:
                    self.current_output.append(text_line)
            except Exception:
                break
        self.running = False
        self.task_event.set()

    def send(self, prompt):
        with self.lock:
            if not self.start():
                return None
            self.current_output = []
            self.task_event.clear()

            payload = json.dumps({"type": "user_message", "content": prompt}) + "\n"
            try:
                self.process.stdin.write(payload.encode("utf-8"))
                self.process.stdin.flush()
            except Exception:
                self.running = False
                return None

        # Wait for task completion or timeout
        signaled = self.task_event.wait(timeout=self.timeout)
        output = "\n".join(self.current_output).strip()

        if not signaled:
            self.stop()
            return f"[ERROR] Coding agent timed out after {self.timeout} seconds.\n{output}"

        if not output and self.process and self.process.poll() is not None:
            code = self.process.returncode
            if code != 0:
                return f"[CODING FAILED] Persistent session exited with code {code}."

        return output or "The coding agent returned no text output."

    def stop(self):
        with self.lock:
            self.running = False
            self.task_event.set()
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass
                self.process = None
            if self.stdout_file:
                try:
                    self.stdout_file.close()
                except Exception:
                    pass
            if self.stderr_file:
                try:
                    self.stderr_file.close()
                except Exception:
                    pass


class CodingBackend:
    """Run Claude Code, Codex, Cline, or any user-configured coding CLI."""

    def __init__(self, environ=None, popen_factory=None):
        self.environ = os.environ if environ is None else environ
        self.popen_factory = popen_factory
        self.session = None
        self._session_lock = threading.Lock()

    @staticmethod
    def _read_tail(stream):
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - MAX_OUTPUT_CHARS), os.SEEK_SET)
        return stream.read(MAX_OUTPUT_CHARS).decode("utf-8", errors="replace").strip()

    @property
    def provider(self):
        return str(self.environ.get("JARVIS_CODING_BACKEND", "claude-code")).strip().lower()

    @property
    def workspace(self):
        raw = str(self.environ.get("JARVIS_CODING_WORKSPACE", str(ROOT))).strip()
        return Path(raw).expanduser().resolve()

    @property
    def command_template(self):
        custom = str(self.environ.get("JARVIS_CODING_COMMAND", "")).strip()
        if custom:
            return custom
        return PRESETS.get(self.provider, "")

    @property
    def timeout(self):
        try:
            return max(30, min(int(self.environ.get("JARVIS_CODING_TIMEOUT", DEFAULT_TIMEOUT)), 7200))
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT

    def status(self):
        template = self.command_template
        try:
            argv = shlex.split(template) if template else []
        except ValueError as exc:
            return {"configured": False, "provider": self.provider, "error": str(exc)}
        executable = argv[0] if argv else ""
        resolved = shutil.which(executable) if executable else None
        return {
            "configured": bool(argv and "{prompt}" in template),
            "provider": self.provider,
            "workspace": str(self.workspace),
            "command": template,
            "executable": executable or None,
            "available": bool(resolved),
            "timeout": self.timeout,
            "persistent_running": bool(self.session and self.session.running),
        }

    def start(self):
        """Start the persistent background coding session."""
        status = self.status()
        if not status["configured"] or not status["available"]:
            return False
        workspace = self.workspace
        if not workspace.is_dir():
            return False
        try:
            parts = shlex.split(self.command_template)
            # Remove prompt placeholder for persistent initialization argv
            argv = [p for p in parts if p != "{prompt}"]
        except Exception:
            return False

        with self._session_lock:
            if self.session and self.session.running:
                return True
            self.session = PersistentCodingSession(
                argv, workspace, self.timeout, popen_factory=self.popen_factory
            )
            print(f"[CODING] Starting persistent {self.provider} session in {workspace}", flush=True)
            return self.session.start()

    def stop(self):
        """Stop the persistent background coding session."""
        with self._session_lock:
            if self.session:
                self.session.stop()
                self.session = None

    def run(self, prompt):
        prompt = str(prompt or "").strip()
        if not prompt:
            return "[ERROR] Give the coding agent a task."
        if len(prompt) > MAX_PROMPT_CHARS:
            return f"[ERROR] Coding task exceeds {MAX_PROMPT_CHARS} characters."
        status = self.status()
        if not status["configured"]:
            return (
                "[ERROR] Coding backend is not configured. Run "
                "`jarvis-setup coding` and set a command containing {prompt}."
            )
        if not status["available"]:
            return f"[ERROR] Coding CLI not found: {status['executable']}. Install it or update JARVIS_CODING_COMMAND."
        workspace = self.workspace
        if not workspace.is_dir():
            return f"[ERROR] Coding workspace does not exist: {workspace}"

        # Ensure persistent session is running
        if not self.start():
            return f"[ERROR] Could not start persistent coding session for {self.provider}."

        print(f"[CODING] Sending task to persistent {self.provider} session", flush=True)
        result = self.session.send(prompt)
        if result is not None:
            return f"[CODING COMPLETE] Backend: {self.provider}\nWorkspace: {workspace}\n{result}"

        # Fallback to one-shot if persistent send failed
        self.stop()
        if not self.start():
            return f"[ERROR] Persistent coding session failed and restart failed."

        result = self.session.send(prompt)
        if result is not None:
            return f"[CODING COMPLETE] Backend: {self.provider}\nWorkspace: {workspace}\n{result}"

        return f"[CODING FAILED] Persistent coding session did not return output."
