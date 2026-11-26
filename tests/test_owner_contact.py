import tempfile
import unittest
from pathlib import Path

from automation.owner_contact import OwnerContactManager


class FakeOwnerContactManager(OwnerContactManager):
    def __init__(self, state_path):
        super().__init__(state_path=state_path)
        self.sent = []

    def _send(self, payload):
        self.sent.append(payload)
        return {"ok": True, "accepted": True}


class OwnerContactTests(unittest.TestCase):
    def test_duplicate_event_is_suppressed(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeOwnerContactManager(Path(directory) / "events.json")
            first = manager.request_call(
                "report_ready", "The report is ready.", event_id="report-42"
            )
            second = manager.request_call(
                "report_ready", "The report is ready.", event_id="report-42"
            )
            self.assertTrue(first["delivered"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(len(manager.sent), 1)

    def test_distinct_events_are_not_suppressed(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeOwnerContactManager(Path(directory) / "events.json")
            manager.request_call("task", "Task one", event_id="task-1")
            manager.request_call("task", "Task two", event_id="task-2")
            self.assertEqual(len(manager.sent), 2)

    def test_priority_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeOwnerContactManager(Path(directory) / "events.json")
            with self.assertRaises(ValueError):
                manager.request_call("task", "Task", priority="critical")


if __name__ == "__main__":
    unittest.main()
