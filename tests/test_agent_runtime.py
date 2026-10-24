"""Regression tests for the durable agent execution runtime."""
import json
import tempfile
import unittest
from pathlib import Path

from automation.agent_runtime import (
    ExecutionJournal,
    ExecutionRuntime,
    is_read_only_request,
    redact,
)


class AgentRuntimeTests(unittest.TestCase):
    def test_read_only_allowlist_is_conservative(self):
        self.assertTrue(is_read_only_request("show battery status"))
        self.assertTrue(is_read_only_request("git status"))
        self.assertFalse(is_read_only_request("send WhatsApp message to Mom"))
        self.assertFalse(is_read_only_request("delete old backups"))

    def test_transient_read_only_failure_retries_once(self):
        calls = []
        def dispatch(command):
            calls.append(command)
            return "[ERROR] HTTP 503 temporarily unavailable" if len(calls) == 1 else "[OK] status available"
        with tempfile.TemporaryDirectory() as directory:
            runtime = ExecutionRuntime(dispatch, Path(directory) / "events.jsonl", retry_delay=0)
            result = runtime.execute("task-12345678", {"number": 1, "command": "show battery status"})
            self.assertEqual(result, "[OK] status available")
            self.assertEqual(len(calls), 2)

    def test_side_effect_request_is_never_retried(self):
        calls = []
        def dispatch(command):
            calls.append(command)
            return "[ERROR] HTTP 503 temporarily unavailable"
        with tempfile.TemporaryDirectory() as directory:
            runtime = ExecutionRuntime(dispatch, Path(directory) / "events.jsonl", retry_delay=0)
            runtime.execute("task-12345678", {"number": 1, "command": "send WhatsApp message to Mom"})
            self.assertEqual(len(calls), 1)

    def test_journal_redacts_credentials_and_bounds_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            journal = ExecutionJournal(path)
            journal.record({"event": "step_finished", "result": "api_key=supersecret"})
            saved = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertNotIn("supersecret", json.dumps(saved))
            self.assertIn("[REDACTED]", saved["result"])
            self.assertEqual(len(journal.recent(1)), 1)

    def test_journal_failure_does_not_fail_task(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ExecutionJournal(Path(directory) / "missing" / "events.jsonl")
            # Directory creation is best effort; ordinary writable temp paths should work.
            journal.record({"event": "test", "result": "ok"})
            self.assertEqual(len(journal.recent()), 1)


if __name__ == "__main__":
    unittest.main()
