"""Tests that live screen frames are described locally before Groq reasoning."""
import unittest
from unittest.mock import patch

from screen_cast import perception


class FakeMirage:
    def describe_bytes(self, frame):
        assert frame == b"ephemeral-jpeg"
        return {
            "ok": True,
            "reasoning": "Android settings screen",
            "objects": [{"label": "settings panel"}],
        }


class LocalScreenPerceptionTests(unittest.TestCase):
    def test_groq_receives_local_text_description_not_raw_frame(self):
        captured = []

        def ask(prompt):
            captured.append(prompt)
            return "Settings screen."

        with patch.object(perception, "_MIRAGE_ENGINE", FakeMirage()):
            result = perception._ask_screen("Describe screen", ask, b"ephemeral-jpeg")

        self.assertEqual(result, "Settings screen.")
        self.assertEqual(len(captured), 1)
        self.assertIn("Android settings screen", captured[0])
        self.assertNotIn("ephemeral-jpeg", captured[0])

    def test_no_frame_is_reported_without_loading_model(self):
        captured = []
        result = perception._ask_screen("Describe screen", captured.append, None)
        self.assertEqual(result, "")
        self.assertIn("no fresh live frame", captured[0])


if __name__ == "__main__":
    unittest.main()
