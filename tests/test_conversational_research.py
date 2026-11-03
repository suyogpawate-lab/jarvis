import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from automation.conversational_research import ConversationalResearch
from core.temporal_context import build_temporal_context


class ConversationalResearchTests(unittest.TestCase):
    def test_parses_immediate_research(self):
        parsed = ConversationalResearch.parse_request(
            "Research the latest developments in robotics"
        )
        self.assertEqual(parsed["timing"], "now")
        self.assertIn("robotics", parsed["query"])

    def test_parses_tonight_and_explicit_time(self):
        tonight = ConversationalResearch.parse_request(
            "Research semiconductor advances tonight and brief me"
        )
        self.assertEqual(tonight["timing"], "tonight")
        at_time = ConversationalResearch.parse_request(
            "Research robotics at 7:30 pm"
        )
        self.assertEqual(at_time["timing"], "at")
        self.assertEqual(at_time["schedule_at"], "at 7:30 pm")
        self.assertNotIn("7:30", at_time["query"])

    def test_monitoring_request_becomes_daily_recurrence(self):
        parsed = ConversationalResearch.parse_request(
            "Keep track of semiconductor developments and notify me when something significant happens"
        )
        self.assertEqual(parsed["timing"], "daily")
        self.assertIn("semiconductor", parsed["query"])

    def test_scheduled_research_uses_local_timezone_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConversationalResearch(Mock(), Mock(), Path(directory) / "missions.json")
            scheduler = Mock()
            scheduler.schedule.return_value = {"id": "auto-1234abcd", "next_run": 1790000000}
            zone = ZoneInfo("Asia/Kolkata")
            response = manager.schedule("robotics", "at", scheduler, zone, "at 7:30 pm")
            self.assertIn("auto-1234abcd", response)
            args = scheduler.schedule.call_args.kwargs
            self.assertEqual(args["command"], "research robotics")
            saved = json.loads((Path(directory) / "missions.json").read_text())
            self.assertEqual(saved[0]["status"], "SCHEDULED")

    def test_research_records_provider_failures_and_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            provider_ok = Mock()
            provider_ok.name = "provider_ok"
            provider_ok.search.return_value = [SimpleNamespace(source="provider_ok", title="Robotics paper", url="https://example.org/paper")]
            provider_bad = Mock()
            provider_bad.name = "provider_bad"
            provider_bad.search.side_effect = RuntimeError("offline")
            hub = Mock()
            hub.providers = [provider_ok, provider_bad]
            hub.search.return_value = [SimpleNamespace(source="provider_ok", title="Robotics paper", url="https://example.org/paper")]
            deep = Mock()
            deep.search.return_value = "Evidence-based summary."
            manager = ConversationalResearch(hub, deep, Path(directory) / "missions.json")
            answer = manager.research_now("robotics")
            self.assertIn("provider_bad", answer)
            saved = json.loads((Path(directory) / "missions.json").read_text())
            self.assertEqual(saved[0]["status"], "COMPLETED")
            self.assertEqual(saved[0]["provider_failures"][0]["name"], "provider_bad")
            self.assertEqual(saved[0]["sources"][0]["url"], "https://example.org/paper")

    def test_temporal_context_uses_scheduler_timezone_and_jobs(self):
        zone = ZoneInfo("Asia/Kolkata")
        scheduler = Mock()
        scheduler.timezone = zone
        scheduler.timezone_name = "Asia/Kolkata"
        scheduler.list.return_value = [{
            "status": "SCHEDULED", "next_run": datetime(2026, 11, 4, 9, 0, tzinfo=zone).timestamp(),
            "description": "Research robotics",
        }]
        value = build_temporal_context(scheduler, now=datetime(2026, 11, 3, 18, 0, tzinfo=zone))
        self.assertIn("Asia/Kolkata", value)
        self.assertIn("Research robotics", value)
        self.assertIn("2026-11-03", value)


if __name__ == "__main__":
    unittest.main()
