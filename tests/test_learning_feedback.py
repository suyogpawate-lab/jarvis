"""Tests for explicit preference capture and DPO export."""
import json
import tempfile
import unittest
from pathlib import Path

from learning.feedback_store import FeedbackStore


class FeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = FeedbackStore(root / "preferences.jsonl", root / "export.jsonl")

    def test_no_automatic_capture_and_empty_export(self):
        self.assertIn("0", self.store.status())
        self.assertEqual(self.store.export_dpo(), "[LEARNING] No preference pairs to export.")

    def test_explicit_preference_is_saved_and_exported_in_dpo_shape(self):
        self.store.add_preference(
            "Explain recursion", "A clear base-case explanation", "An incorrect explanation"
        )
        self.assertIn("1", self.store.status())
        result = self.store.export_dpo()
        self.assertIn("1 preference pair", result)
        exported = json.loads(self.store.export_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(set(exported), {"prompt", "chosen", "rejected"})
        self.assertEqual(exported["chosen"], "A clear base-case explanation")

    def test_identical_answers_are_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add_preference("Prompt", "Same", "Same")

    def test_command_requires_three_explicit_fields(self):
        result = self.store.handle("/learn prefer prompt || chosen")
        self.assertIn("Use:", result)
        self.assertFalse(self.store.path.exists())


if __name__ == "__main__":
    unittest.main()
