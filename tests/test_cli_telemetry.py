"""Tests for privacy-conscious plain-CLI telemetry."""
import os
import unittest
from unittest.mock import patch

from monitoring.cli_telemetry import (
    begin_turn, finish_turn, format_cli_summary,
    record_model_usage, record_tool_usage,
)


class CliTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.disabled = patch.dict(os.environ, {"JARVIS_CLI_TELEMETRY": "0"})
        self.disabled.start()
        self.addCleanup(self.disabled.stop)
        begin_turn()

    def test_records_model_tokens_and_explicit_tool_verification(self):
        record_model_usage("groq", "test-model", {
            "prompt_tokens": 120, "completion_tokens": 45,
        }, 180.5)
        record_tool_usage("battery_status", {"ok": True, "verified": True})
        result = finish_turn(1.25)
        self.assertEqual(result["input_tokens"], 120)
        self.assertEqual(result["output_tokens"], 45)
        self.assertEqual(result["verification_percent"], 100)
        self.assertEqual(result["tools"], ["battery_status"])
        self.assertIn("1.25s", format_cli_summary(result))

    def test_does_not_invent_confidence_when_no_tool_reports_verification(self):
        record_tool_usage("plain_search", {"ok": True})
        result = finish_turn(0.5)
        self.assertIsNone(result["verification_percent"])
        self.assertIn("not scored", format_cli_summary(result))

    def test_failed_tool_is_counted_as_failure(self):
        record_tool_usage("screen_view", {"ok": False, "error": "offline"})
        result = finish_turn(0.5)
        self.assertEqual(result["tool_total"], 1)
        self.assertEqual(result["tool_successes"], 0)


if __name__ == "__main__":
    unittest.main()
