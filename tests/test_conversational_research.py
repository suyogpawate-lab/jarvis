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
            manager._knowledge_hub_search = Mock(return_value=[])
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

    def test_knowledge_hub_matches_are_recorded_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConversationalResearch(Mock(), Mock(), Path(directory) / "missions.json")
            manager._knowledge_hub_search = Mock(return_value=[{
                "provider": "knowledge_hub", "title": "Robotics notes",
                "snippet": "Local notes about robotics.", "chunk_no": 2,
            }])
            manager.search_hub.providers = []
            manager.deep_search.search.return_value = "Web synthesis."
            answer = manager.research_now("robotics")
            self.assertIn("Local Knowledge Hub matches", answer)
            saved = json.loads((Path(directory) / "missions.json").read_text())
            self.assertEqual(saved[0]["local_evidence"][0]["chunk_no"], 2)

    def test_second_run_only_notifies_for_new_source_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = Mock()
            provider.name = "test"
            provider.search.return_value = [
                SimpleNamespace(title="Known", url="https://example.org/a"),
            ]
            hub = Mock()
            hub.providers = [provider]
            deep = Mock()
            deep.search.return_value = "Supported summary."
            manager = ConversationalResearch(hub, deep, Path(directory) / "missions.json")
            manager._knowledge_hub_search = Mock(return_value=[])
            first = manager.research_now("robotics")
            second = manager.research_now("robotics")
            self.assertIn("Research complete", first)
            self.assertIn("no new source URLs", second)

    def test_whatsapp_alert_requires_explicit_owner_number_and_worker(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            manager = ConversationalResearch(Mock(), Mock(), Path(directory) / "missions.json")
            manager.set_whatsapp_sender(lambda recipient, message: {"id": "sent"})
            with patch.dict(os.environ, {"JARVIS_WA_RESEARCH_NOTIFY_TO": "919876543210"}), \
                 patch("shutil.which", return_value=None):
                result = manager._send_monitor_notification("JARVIS", "Update", "alert-1")
            self.assertTrue(result["ok"])
            self.assertEqual(result["channels"]["whatsapp"]["ok"], True)

    def test_whatsapp_alert_does_not_guess_a_recipient(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            manager = ConversationalResearch(Mock(), Mock(), Path(directory) / "missions.json")
            manager.set_whatsapp_sender(lambda *args: self.fail("must not send without opt-in"))
            with patch.dict(os.environ, {}, clear=True), patch("shutil.which", return_value=None):
                result = manager._send_monitor_notification("JARVIS", "Update", "alert-2")
            self.assertFalse(result["ok"])
            self.assertEqual(result["channels"]["whatsapp"]["error"], "not configured")

    def test_cancel_scheduled_research(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConversationalResearch(Mock(), Mock(), Path(directory) / "missions.json")
            manager._record({
                "id": "research-123", "automation_id": "auto-123",
                "query": "robotics", "status": "SCHEDULED",
            })
            scheduler = Mock()
            scheduler.cancel.return_value = {"id": "auto-123", "status": "CANCELLED"}
            answer = manager.cancel_mission("auto-123", scheduler)
            self.assertIn("cancelled", answer)
            self.assertEqual(manager.list_missions()[0]["status"], "CANCELLED")
            scheduler.cancel.assert_called_once_with("auto-123")


if __name__ == "__main__":
    unittest.main()
