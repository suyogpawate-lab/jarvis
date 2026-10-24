"""Regression tests for the reliability issues found in the repository audit."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from android import command_guard
from automation.job_manager import JobManager
from automation.scheduler import AutomationScheduler
from automation.task_executor import TaskExecutor
from search.deep_search import DeepSearch
from tools.mcp_client import MCPError, MCPServer


class TaskExecutorRegressionTests(unittest.TestCase):
    def test_nonzero_shell_exit_line_is_failure(self):
        self.assertTrue(TaskExecutor._is_failure("[EXEC] false\n[EXIT] 1"))
        self.assertFalse(TaskExecutor._is_failure("[EXEC] true\n[EXIT] 0"))

    def test_structured_exit_codes_are_checked(self):
        self.assertTrue(TaskExecutor._is_failure({"exit_code": 2}))
        self.assertFalse(TaskExecutor._is_failure({"ok": True, "exit_code": 0}))

    def test_task_approval_authorizes_exact_risky_command_once(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(command_guard, "PENDING_FILE", Path(temp) / "pending.json"), \
                 patch.dict(os.environ, {"JARVIS_SHELL_POLICY": "strict"}):
                command = "rm -f /tmp/jarvis-audit-test"
                self.assertTrue(command_guard.requires_approval(command))
                command_guard.authorize_command_once(command)
                self.assertIsNone(command_guard.check(command))
                # Authorization is one-shot; a second attempt requires its own approval.
                self.assertIsNotNone(command_guard.check(command))

    def test_task_level_approval_does_not_trigger_a_second_guard_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(command_guard, "PENDING_FILE", Path(temp) / "pending.json"), \
                 patch.dict(os.environ, {"JARVIS_SHELL_POLICY": "strict"}):
                def dispatch(command):
                    verdict = command_guard.check(command)
                    return verdict or "[EXEC] test\n[EXIT] 0"
                executor = TaskExecutor(dispatch, task_dir=Path(temp) / "tasks")
                created = executor.handle("/task plan rm -f /tmp/jarvis-audit-test")
                task_id = created.split()[2]
                executor.handle(f"/task run {task_id}", source="text")
                result = executor.handle(f"/task approve {task_id}", source="text")
                self.assertIn("Task " + task_id + " — COMPLETED", result)
                self.assertNotIn("[NEEDS_APPROVAL]", result)


class BackgroundJobRegressionTests(unittest.TestCase):
    def test_nonzero_exit_code_is_failed_even_without_stderr(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = JobManager(base_dir=temp)
            marker = Path(temp) / "job.exit"
            marker.write_text("7", encoding="ascii")
            job = {
                "id": "job",
                "pid": 123,
                "status": "RUNNING",
                "stderr_file": str(Path(temp) / "job.stderr"),
                "exit_code_file": str(marker),
            }
            with patch("automation.job_manager.subprocess.run", return_value=SimpleNamespace(stdout="")):
                refreshed = manager._refresh(job)
            self.assertEqual(refreshed["status"], "FAILED")
            self.assertEqual(refreshed["exit_code"], 7)


class SchedulerRegressionTests(unittest.TestCase):
    def test_custom_base_dir_is_honored_and_error_result_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            scheduler = AutomationScheduler(lambda _: "[ERROR] callback failed", base_dir=temp)
            try:
                self.assertEqual(scheduler.base_dir, os.path.abspath(temp))
                item = {
                    "id": "auto-test",
                    "command": "test",
                    "repeat_seconds": None,
                    "repeat_mode": None,
                    "next_run": 1,
                    "status": "SCHEDULED",
                    "run_count": 0,
                }
                scheduler._execute(item)
                self.assertEqual(item["status"], "FAILED")
                self.assertEqual(item["last_status"], "FAILED")
                self.assertTrue((Path(temp) / "auto-test.json").is_file())
            finally:
                scheduler.shutdown()

    def test_structured_failure_is_recognized(self):
        self.assertTrue(AutomationScheduler._result_failed({"ok": False, "error": "no"}))
        self.assertTrue(AutomationScheduler._result_failed("[EXIT] 3"))
        self.assertFalse(AutomationScheduler._result_failed({"ok": True, "exit_code": 0}))


class MCPTransportRegressionTests(unittest.TestCase):
    def test_send_after_server_close_raises_controlled_error(self):
        server = MCPServer("closed", "unused")
        with self.assertRaises(MCPError):
            server._send({"jsonrpc": "2.0", "method": "ping"})


class DeepSearchRegressionTests(unittest.TestCase):
    def test_mobile_safe_bounded_defaults(self):
        search = DeepSearch(search_hub=object(), fast_agent=object())
        self.assertEqual(search.max_pages, 12)
        self.assertEqual(search.max_depth, 2)
        self.assertEqual(search.max_seconds, 120)
        self.assertEqual(search.max_evidence_chars, 24000)


if __name__ == "__main__":
    unittest.main()
