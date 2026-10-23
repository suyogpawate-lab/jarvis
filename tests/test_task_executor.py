"""Regression tests for safe multi-step task execution."""
import tempfile
import unittest
from pathlib import Path

from automation.task_executor import TaskExecutor


class TaskExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.calls = []
        self.executor = TaskExecutor(
            dispatch=self.dispatch,
            task_dir=Path(self.temp_dir.name),
        )

    def dispatch(self, command):
        self.calls.append(command)
        return f"[OK] executed: {command}"

    def task_id(self, response):
        return response.split()[2]

    def test_plan_is_persisted_and_bounded(self):
        response = self.executor.handle("/task plan check battery || check storage")
        task_id = self.task_id(response)
        self.assertIn("[TASK CREATED]", response)
        self.assertEqual(self.executor._load(task_id)["status"], "PLANNED")
        self.assertEqual(len(self.executor._load(task_id)["steps"]), 2)
        too_many = self.executor.create([f"step {i}" for i in range(11)])
        self.assertIn("[ERROR]", too_many)

    def test_safe_steps_run_in_order_and_complete(self):
        created = self.executor.handle("/task plan check battery || check storage")
        task_id = self.task_id(created)
        report = self.executor.handle(f"/task run {task_id}")
        self.assertEqual(self.calls, ["check battery", "check storage"])
        self.assertIn("Task " + task_id + " — COMPLETED", report)

    def test_consequential_step_pauses_until_one_step_approval(self):
        created = self.executor.handle(
            "/task plan check battery || send WhatsApp message to Alex || check storage"
        )
        task_id = self.task_id(created)
        report = self.executor.handle(f"/task run {task_id}")
        self.assertEqual(self.calls, ["check battery"])
        self.assertIn("WAITING_APPROVAL", report)
        self.assertIn("/task approve " + task_id, report)
        report = self.executor.handle(f"/task approve {task_id}")
        self.assertEqual(
            self.calls,
            ["check battery", "send WhatsApp message to Alex", "check storage"],
        )
        self.assertIn("COMPLETED", report)

    def test_failure_stops_remaining_steps(self):
        self.executor.dispatch = lambda command: (
            self.calls.append(command) or "[ERROR] simulated failure"
        )
        task_id = self.task_id(self.executor.handle("/task plan first step || second step"))
        report = self.executor.handle(f"/task run {task_id}")
        self.assertEqual(self.calls, ["first step"])
        self.assertIn("FAILED", report)
        self.assertNotIn("second step", self.calls)

    def test_deny_cancels_without_running_pending_action(self):
        created = self.executor.handle("/task plan send WhatsApp message to Alex || check storage")
        task_id = self.task_id(created)
        self.executor.handle(f"/task run {task_id}")
        report = self.executor.handle(f"/task deny {task_id}")
        self.assertEqual(self.calls, [])
        self.assertIn("CANCELLED", report)

    def test_nested_task_commands_are_rejected(self):
        response = self.executor.handle("/task plan /task run task-12345678 || check storage")
        self.assertIn("[ERROR]", response)
        self.assertIn("Nested /task", response)

    def test_invalid_ids_and_unknown_tasks_are_rejected(self):
        self.assertIn("[ERROR]", self.executor.handle("/task status ../secret"))
        self.assertIn("[ERROR]", self.executor.handle("/task run task-deadbeef"))


if __name__ == "__main__":
    unittest.main()
