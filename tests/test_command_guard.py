import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from android import command_guard


class CommandGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pending = Path(self.temp.name) / "pending.json"
        self.env = patch.dict(os.environ, {"JARVIS_SHELL_POLICY": "strict"})
        self.env.start()
        self.file_patch = patch.object(command_guard, "PENDING_FILE", self.pending)
        self.file_patch.start()

    def tearDown(self):
        self.file_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_risky_command_requires_approval(self):
        result = command_guard.check("echo safe && echo second", kind="shell")
        self.assertIn("[NEEDS_APPROVAL]", result)

    def test_approval_is_bound_to_execution_kind(self):
        command = "echo safe && echo second"
        first = command_guard.check(command, kind="shell")
        code = first.split("approve ", 1)[1].split()[0]
        job_result = command_guard.check(command, kind="job")
        self.assertIn("[NEEDS_APPROVAL]", job_result)
        with patch("android.shell_executor.ShellExecutor.execute", return_value="[MOCK EXEC]"):
            self.assertIn("Approved.", command_guard.handle_user_reply("approve " + code))
        # ShellExecutor consumes the approval; it must not authorize a job.
        job_after_shell_approval = command_guard.check(command, kind="job")
        self.assertIn("[NEEDS_APPROVAL]", job_after_shell_approval)

    def test_hard_deny_cannot_be_approved(self):
        result = command_guard.check("mkfs /dev/null", kind="shell")
        self.assertIn("[BLOCKED]", result)


if __name__ == "__main__":
    unittest.main()
