"""Tests for local-only mission recall and diagnosis."""
import json
import tempfile
import unittest
from pathlib import Path

from automation.mission_insights import MissionInsights


class MissionInsightsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.insights = MissionInsights(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def write_task(self, task_id, status, steps, **extra):
        record = {
            "id": task_id,
            "goal": extra.pop("goal", "inspect device battery"),
            "status": status,
            "created_at": 100,
            "updated_at": 200,
            "steps": steps,
            **extra,
        }
        (self.root / f"{task_id}.json").write_text(json.dumps(record), encoding="utf-8")

    def test_empty_history_is_helpful(self):
        self.assertIn("no saved tasks", self.insights.insights())

    def test_insights_count_outcomes_and_repeated_failures(self):
        for task_id in ("task-aaaaaaaa", "task-bbbbbbbb"):
            self.write_task(task_id, "FAILED", [
                {"number": 1, "command": "show battery status", "status": "FAILED", "result": "[ERROR] unavailable"}
            ])
        self.write_task("task-cccccccc", "COMPLETED", [
            {"number": 1, "command": "show battery status", "status": "COMPLETED"}
        ])
        report = self.insights.insights()
        self.assertIn("completed: 1", report)
        self.assertIn("failed: 2", report)
        self.assertIn("2× show battery status", report)
        self.assertIn("no model/API request", report)

    def test_diagnose_failure_does_not_execute(self):
        self.write_task("task-1234abcd", "FAILED", [
            {"number": 1, "command": "read status", "status": "COMPLETED"},
            {"number": 2, "command": "install package", "status": "FAILED", "result": "[ERROR] network unavailable"},
        ], failure="Step 2 failed")
        report = self.insights.diagnose("task-1234abcd")
        self.assertIn("install package", report)
        self.assertIn("network unavailable", report)
        self.assertIn("correct the cause", report)

    def test_recall_finds_prior_commands_and_redacts_secret_values(self):
        self.write_task("task-1234abcd", "COMPLETED", [
            {"number": 1, "command": "show battery status", "status": "COMPLETED", "result": "api_key=supersecret"}
        ])
        report = self.insights.recall("battery")
        self.assertIn("task-1234abcd", report)
        self.assertIn("[REDACTED]", report)
        self.assertNotIn("supersecret", report)

    def test_bad_ids_and_empty_queries_are_rejected(self):
        self.assertIn("Invalid task ID", self.insights.diagnose("../../bad"))
        self.assertIn("Usage:", self.insights.recall("   "))

    def test_malformed_task_files_are_skipped(self):
        (self.root / "task-deadbeef.json").write_text("{not json", encoding="utf-8")
        (self.root / "not-a-task.json").write_text("{}", encoding="utf-8")
        self.assertIn("no saved tasks", self.insights.insights())

    def test_malformed_timestamps_do_not_break_history(self):
        self.write_task("task-1234abcd", "COMPLETED", [], updated_at="not-a-number")
        self.assertIn("Saved tasks: 1", self.insights.insights())
        self.assertIn("task-1234abcd", self.insights.recall("battery"))


if __name__ == "__main__":
    unittest.main()
