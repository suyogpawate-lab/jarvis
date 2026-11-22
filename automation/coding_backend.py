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

    def __init__(self, environ=None, runner=None):
        self.environ = os.environ if environ is None else environ
        self.runner = subprocess.run if runner is None else runner

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
        try:
            result = self.runner(
                argv,
                cwd=str(workspace),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"[ERROR] Coding agent timed out after {self.timeout} seconds. Check the workspace for partial changes."
        except FileNotFoundError:
            return f"[ERROR] Coding CLI not found: {argv[0]}"
        except OSError as exc:
            return f"[ERROR] Could not launch coding agent: {type(exc).__name__}: {exc}"
        output = "\n".join(
            part.strip() for part in (result.stdout or "", result.stderr or "") if part.strip()
        )
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n[Output truncated.]"
        if result.returncode:
            return f"[CODING FAILED] {self.provider} exited with code {result.returncode}.\n{output}"
        return f"[CODING COMPLETE] Backend: {self.provider}\nWorkspace: {workspace}\n{output or 'The coding agent returned no text output.'}"
