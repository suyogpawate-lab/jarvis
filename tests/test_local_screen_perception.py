"""Tests that live screen frames are classified locally before Groq reasoning."""
import unittest
from unittest.mock import patch

from screen_cast import perception


class FakeVision:
    def classify_bytes(self, frame, top_k=5):
        assert frame == b"ephemeral-jpeg"
        return {
            "ok": True,
            "labels": [{"label": "Android settings screen", "score": 0.91}],
        }


class LocalScreenPerceptionTests(unittest.TestCase):
    def test_groq_receives_text_labels_not_raw_frame(self):
        captured = []

        def ask(prompt):
            captured.append(prompt)
            return "Settings screen."

        with patch.object(perception, "_VISION_ENGINE", FakeVision()):
            result = perception._ask_screen("Describe screen", ask, b"ephemeral-jpeg")

        self.assertEqual(result, "Settings screen.")
        self.assertEqual(len(captured), 1)
        self.assertIn("Android settings screen", captured[0])
        self.assertNotIn("ephemeral-jpeg", captured[0])

    def test_no_frame_is_reported_without_loading_model(self):
        captured = []
        result = perception._ask_screen("Describe screen", captured.append, None)
        self.assertIsNone(result)
        self.assertIn("no fresh live frame", captured[0])


if __name__ == "__main__":
    unittest.main()
