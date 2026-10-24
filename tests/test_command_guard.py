"""Regression tests for shell command approval policy."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from android import command_guard


class CommandGuardPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.pending = Path(self.tempdir.name) / "pending.json"
        self.env = patch.dict(os.environ, {"JARVIS_SHELL_POLICY": "strict"})
        self.env.start()
        self.file_patch = patch.object(command_guard, "PENDING_FILE", self.pending)
        self.file_patch.start()

    def tearDown(self):
        self.file_patch.stop()
        self.env.stop()
        self.tempdir.cleanup()

    def test_composed_shell_command_runs_without_approval(self):
        self.assertIsNone(command_guard.check("cd ~/jarvis && python -m unittest"))

    def test_redirection_and_inline_script_do_not_require_approval(self):
        self.assertIsNone(command_guard.check("printf 'ok' > /tmp/jarvis-test.txt"))
        self.assertIsNone(command_guard.check("python -c 'print(1 + 1)'"))

    def test_file_deletion_requires_approval(self):
        result = command_guard.check("rm ./temporary.txt")
        self.assertIn("[NEEDS_APPROVAL]", result)
        self.assertIn("deletes files", result)

    def test_formatting_is_hard_blocked(self):
        result = command_guard.check("mkfs.ext4 /dev/example")
        self.assertIn("[BLOCKED]", result)
        self.assertIn("NOT run", result)

    def test_recursive_delete_is_confirmation_gated_not_silently_run(self):
        result = command_guard.check("rm -rf /tmp/jarvis-test-folder")
        self.assertIn("[NEEDS_APPROVAL]", result)


if __name__ == "__main__":
    unittest.main()
