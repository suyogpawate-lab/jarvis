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


class CodingBackend:
    """Run Claude Code, Codex, Cline, or any user-configured coding CLI."""

    def __init__(self, environ=None, popen_factory=None):
        self.environ = os.environ if environ is None else environ
        self.popen_factory = subprocess.Popen if popen_factory is None else popen_factory

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
        }

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
        try:
            parts = shlex.split(self.command_template)
            argv = [
                part.replace("{prompt}", prompt).replace("{workspace}", str(workspace))
                for part in parts
            ]
        except ValueError as exc:
            return f"[ERROR] Invalid coding command template: {exc}"
        if not any("{prompt}" in part for part in parts):
            return "[ERROR] JARVIS_CODING_COMMAND must contain the {prompt} placeholder."
        print(f"[CODING] {self.provider} working in {workspace}", flush=True)
        # Keep verbose CLI output on disk, not in unbounded RAM buffers.
        try:
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                process = self.popen_factory(
                    argv,
                    cwd=str(workspace),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                )
                try:
                    return_code = process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    output = "\n".join(
                        part for part in (self._read_tail(stdout_file), self._read_tail(stderr_file)) if part
                    )
                    return (
                        f"[ERROR] Coding agent timed out after {self.timeout} seconds. "
                        "Check the workspace for partial changes.\n" + output
                    )
                output = "\n".join(
                    part for part in (self._read_tail(stdout_file), self._read_tail(stderr_file)) if part
                )
        except FileNotFoundError:
            return f"[ERROR] Coding CLI not found: {argv[0]}"
        except OSError as exc:
            return f"[ERROR] Could not launch coding agent: {type(exc).__name__}: {exc}"
        if return_code:
            return f"[CODING FAILED] {self.provider} exited with code {return_code}.\n{output}"
        return f"[CODING COMPLETE] Backend: {self.provider}\nWorkspace: {workspace}\n{output or 'The coding agent returned no text output.'}"
