import unittest
from workspace.manager import WorkspaceManager


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.manager = WorkspaceManager()

    def test_six_surface_limit(self):
        for i in range(6):
            self.manager.open_surface("task", f"Task {i}")
        with self.assertRaises(OverflowError):
            self.manager.open_surface("task", "seventh")

    def test_close_surface(self):
        item = self.manager.open_surface("task", "Research")
        self.assertTrue(self.manager.close_surface(item["id"]))
        self.assertFalse(self.manager.close_surface(item["id"]))

    def test_reject_unsafe_embeds(self):
        for url in ("file:///etc/passwd", "javascript:alert(1)", "http://127.0.0.1:21339/screen"):
            with self.assertRaises(ValueError):
                self.manager.open_surface("web", "unsafe", url)

    def test_telemetry_is_bounded(self):
        result = self.manager.telemetry({"input_tokens": -1, "output_tokens": 42, "confidence": 1.7})
        self.assertIsNone(result["input_tokens"])
        self.assertEqual(result["output_tokens"], 42)
        self.assertIsNone(result["confidence"])

    def test_task_events(self):
        item = self.manager.task_event("task-1", "Research", "active", "Searching")
        self.assertEqual(item["status"], "active")
        self.assertTrue(self.manager.events_after(0))


if __name__ == "__main__":
    unittest.main()
