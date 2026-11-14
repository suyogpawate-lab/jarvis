"""Tests for text-only screen reasoning and complete Groq key rotation."""
import os
import unittest
from unittest.mock import patch

from intelligence.groq_reasoner import ask_screen_with_groq, ScreenReasoningError


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class GroqScreenReasonerTests(unittest.TestCase):
    @patch.dict(os.environ, {"GROQ_API_KEYS": "key1,key2,key3", "JARVIS_FAST_MODEL": "openai/gpt-oss-20b"}, clear=True)
    @patch("intelligence.groq_reasoner.requests.post")
    def test_rotates_through_all_keys_until_success(self, post):
        post.side_effect = [
            FakeResponse(429),
            FakeResponse(429),
            FakeResponse(200, {"choices": [{"message": {"content": "Settings screen."}}]}),
        ]
        result = ask_screen_with_groq("Accessibility text only")
        self.assertEqual(result, "Settings screen.")
        self.assertEqual(post.call_count, 3)
        self.assertEqual(post.call_args_list[0].kwargs["headers"]["Authorization"], "Bearer key1")
        self.assertEqual(post.call_args_list[2].kwargs["headers"]["Authorization"], "Bearer key3")
        self.assertEqual(post.call_args_list[2].kwargs["json"]["messages"][1]["content"], "Accessibility text only")

    @patch.dict(os.environ, {"GROQ_API_KEYS": "key1,key2",}, clear=True)
    @patch("intelligence.groq_reasoner.requests.post")
    def test_reports_all_keys_rate_limited(self, post):
        post.side_effect = [FakeResponse(429), FakeResponse(429)]
        with self.assertRaises(ScreenReasoningError) as caught:
            ask_screen_with_groq("text")
        self.assertEqual(caught.exception.code, "all_keys_rate_limited")
        self.assertEqual(post.call_count, 2)

    @patch.dict(os.environ, {}, clear=True)
    @patch("intelligence.groq_reasoner.requests.post")
    def test_reports_missing_credentials(self, post):
        with self.assertRaises(ScreenReasoningError) as caught:
            ask_screen_with_groq("text")
        self.assertEqual(caught.exception.code, "missing_credentials")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
