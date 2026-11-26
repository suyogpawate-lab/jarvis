"""Tests for configurable coding-agent CLI routing and persistent session backend."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.coding_backend import CodingBackend, PersistentCodingSession


class CodingBackendTests(unittest.TestCase):
    def test_claude_code_default_preset(self):
        backend = CodingBackend(environ={"JARVIS_CODING_BACKEND": "claude-code"})
        self.assertEqual(backend.command_template, "claude -p {prompt}")

    def test_codex_default_preset(self):
        backend = CodingBackend(environ={"JARVIS_CODING_BACKEND": "codex"})
        self.assertEqual(backend.command_template, "codex exec {prompt}")

    def test_persistent_session_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def runner(argv, **kwargs):
                calls.append((argv, kwargs))
                # Mock process with stdin/stdout pipes
                stdin_pipe = kwargs.get("stdin")
                stdout_read, stdout_write = subprocess.PIPE, subprocess.PIPE
                # Create a mock process object
                proc = type("Process", (), {
                    "poll": lambda self: None,
                    "terminate": lambda self: None,
                    "kill": lambda self: None,
                    "wait": lambda self, timeout=None: 0,
                    "returncode": 0,
                    "stdin": type("Stdin", (), {"write": lambda s, data: None, "flush": lambda s: None})(),
                    "stdout": type("Stdout", (), {"readline": lambda s: b'{"type":"result","result":"task done"}\n'})(),
                })()
                return proc

            env = {
                "JARVIS_CODING_BACKEND": "custom",
                "JARVIS_CODING_COMMAND": "fake-agent {prompt}",
                "JARVIS_CODING_WORKSPACE": directory,
                "JARVIS_CODING_TIMEOUT": "10",
            }
            backend = CodingBackend(environ=env, popen_factory=runner)
            with patch("automation.coding_backend.shutil.which", return_value="/usr/bin/fake-agent"):
                started = backend.start()
                self.assertTrue(started)
                self.assertTrue(backend.session.running)

                result = backend.run("Fix bug")
                self.assertIn("[CODING COMPLETE]", result)
                self.assertIn("task done", result)

                backend.stop()
                self.assertIsNone(backend.session)

    def test_missing_prompt_placeholder_is_not_executed(self):
        backend = CodingBackend(environ={
            "JARVIS_CODING_BACKEND": "custom",
            "JARVIS_CODING_COMMAND": "my-agent --run",
        })
        self.assertIn("not configured", backend.run("change code"))

    def test_coding_task_classifier(self):
        from automation.command_dispatcher import CommandDispatcher
        self.assertTrue(CommandDispatcher._looks_like_coding_task("Fix the JARVIS WhatsApp parser bug"))
        self.assertTrue(CommandDispatcher._looks_like_coding_task("Build a Python CLI tool"))
        self.assertTrue(CommandDispatcher._looks_like_coding_task("Refactor this repository backend"))
        self.assertTrue(CommandDispatcher._looks_like_coding_task("Can you add a feature to my app?"))
        self.assertTrue(CommandDispatcher._looks_like_coding_task("Please make the JARVIS coding backend use Claude Code"))
        self.assertTrue(CommandDispatcher._looks_like_coding_task("Work on the Python project and fix its tests"))
        self.assertFalse(CommandDispatcher._looks_like_coding_task("Research quantum physics overnight"))
        self.assertFalse(CommandDispatcher._looks_like_coding_task("What is a Python generator?"))
        self.assertFalse(CommandDispatcher._looks_like_coding_task("How do I fix a Python bug?"))
        self.assertFalse(CommandDispatcher._looks_like_coding_task("Explain how a backend works"))


if __name__ == "__main__":
    unittest.main()
