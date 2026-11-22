"""Tests for configurable coding-agent CLI routing."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.coding_backend import CodingBackend
from automation.command_dispatcher import CommandDispatcher


class CodingBackendTests(unittest.TestCase):
    def test_claude_code_default_preset(self):
        backend = CodingBackend(environ={"JARVIS_CODING_BACKEND": "claude-code"})
        self.assertEqual(backend.command_template, "claude -p {prompt}")

    def test_codex_default_preset(self):
        backend = CodingBackend(environ={"JARVIS_CODING_BACKEND": "codex"})
        self.assertEqual(backend.command_template, "codex exec {prompt}")

    def test_custom_cli_receives_prompt_as_single_argument_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def runner(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, "changed files and tests passed", "")
            env = {
                "JARVIS_CODING_BACKEND": "cline",
                "JARVIS_CODING_COMMAND": "fake-cline --prompt {prompt} --cwd {workspace}",
                "JARVIS_CODING_WORKSPACE": directory,
                "JARVIS_CODING_TIMEOUT": "60",
            }
            backend = CodingBackend(environ=env, runner=runner)
            with patch("automation.coding_backend.shutil.which", return_value="/usr/bin/fake-cline"):
                result = backend.run("Fix the parser; then run tests")
            self.assertIn("[CODING COMPLETE]", result)
            argv, kwargs = calls[0]
            self.assertEqual(argv[2], "Fix the parser; then run tests")
            self.assertEqual(argv[-1], str(Path(directory).resolve()))
            self.assertEqual(kwargs["cwd"], str(Path(directory).resolve()))
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["timeout"], 60)
            self.assertNotIn("shell", kwargs)

    def test_missing_prompt_placeholder_is_not_executed(self):
        backend = CodingBackend(environ={
            "JARVIS_CODING_BACKEND": "custom",
            "JARVIS_CODING_COMMAND": "my-agent --run",
        })
        self.assertIn("not configured", backend.run("change code"))

    def test_nonzero_exit_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            def runner(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 2, "", "test failure")
            backend = CodingBackend(environ={
                "JARVIS_CODING_BACKEND": "custom",
                "JARVIS_CODING_COMMAND": "fake-agent {prompt}",
                "JARVIS_CODING_WORKSPACE": directory,
            }, runner=runner)
            with patch("automation.coding_backend.shutil.which", return_value="/usr/bin/fake-agent"):
                result = backend.run("run tests")
            self.assertIn("exited with code 2", result)
            self.assertIn("test failure", result)

    def test_coding_task_classifier(self):
        self.assertTrue(CommandDispatcher._looks_like_coding_task("Fix the JARVIS WhatsApp parser bug"))
        self.assertTrue(CommandDispatcher._looks_like_coding_task("Build a Python CLI tool"))
        self.assertTrue(CommandDispatcher._looks_like_coding_task("Refactor this repository backend"))
        self.assertFalse(CommandDispatcher._looks_like_coding_task("Research quantum physics overnight"))
        self.assertFalse(CommandDispatcher._looks_like_coding_task("What is a Python generator?"))
        self.assertFalse(CommandDispatcher._looks_like_coding_task("/code status"))


if __name__ == "__main__":
    unittest.main()
