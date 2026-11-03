import tempfile
import unittest
from pathlib import Path
from automation.research_monitor import ResearchMonitor

class ResearchMonitorTests(unittest.TestCase):
    def test_content_change_is_detected_and_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            content = {"value": "version one"}
            monitor = ResearchMonitor(d, fetcher=lambda url: content["value"], notifier=lambda *a: {"ok": True})
            source = [{"url": "https://example.org/article", "title": "Article"}]
            self.assertEqual(monitor.compare(source)[0], [])
            content["value"] = "version two"
            changed, failures = monitor.compare(source)
            self.assertEqual(len(changed), 1)
            self.assertEqual(failures, [])
            self.assertNotEqual(changed[0]["previous_hash"], changed[0]["sha256"])

    def test_fetch_failure_is_reported_without_losing_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            monitor = ResearchMonitor(d, fetcher=lambda url: "stable")
            source = [{"url": "https://example.org/a"}]
            monitor.compare(source)
            broken = ResearchMonitor(d, fetcher=lambda url: (_ for _ in ()).throw(TimeoutError()))
            changed, failures = broken.compare(source)
            self.assertEqual(changed, [])
            self.assertEqual(failures[0]["error"], "TimeoutError")

    def test_significance_score_is_explainable(self):
        assessment = ResearchMonitor.assess("A major discovery demonstrated a breakthrough", [{"url":"a"}], [])
        self.assertEqual(assessment["level"], "important")
        self.assertGreaterEqual(assessment["score"], 35)
        self.assertEqual(assessment["method"], "explainable_event_classification_and_source_delta")\n        self.assertIn("technical_milestone", assessment["signals"])

    def test_failed_notification_retries_with_same_id_and_bounded_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            def notifier(title, content, alert_id):
                sent.append(alert_id)
                return {"ok": len(sent) >= 2}
            monitor = ResearchMonitor(d, notifier=notifier)
            evidence = [{"url": "https://example.org/a", "sha256": "abc"}]
            assessment = {"level": "important", "score": 40}
            first = monitor.notify_once("robotics", evidence, "Update", assessment)
            self.assertFalse(first["sent"])
            rows = monitor._read(monitor.outbox_path)
            rows[0]["retry_at"] = 0
            monitor._write(monitor.outbox_path, rows)
            retried = monitor.retry_pending()
            self.assertTrue(retried[0]["sent"])
            self.assertEqual(sent[0], sent[1])
            self.assertEqual(monitor.status()["pending_notifications"], 0)

    def test_same_url_new_content_has_a_distinct_notification_fingerprint(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            monitor = ResearchMonitor(d, notifier=lambda *args: (sent.append(args) or {"ok": True}))
            assessment = {"level": "important", "score": 40}
            monitor.notify_once("robotics", [{"url": "https://example.org/a", "sha256": "one"}], "Update one", assessment)
            monitor.notify_once("robotics", [{"url": "https://example.org/a", "sha256": "two"}], "Update two", assessment)
            self.assertEqual(len(sent), 2)

    def test_notification_outbox_deduplicates_successful_delivery(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            monitor = ResearchMonitor(d, notifier=lambda *args: (sent.append(args) or {"ok": True}))
            evidence = [{"url": "https://example.org/a"}]
            assessment = {"level": "important", "score": 40}
            first = monitor.notify_once("robotics", evidence, "New development", assessment)
            second = monitor.notify_once("robotics", evidence, "New development", assessment)
            self.assertTrue(first["sent"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(len(sent), 1)
            self.assertEqual(monitor.status()["pending_notifications"], 0)

if __name__ == "__main__":
    unittest.main()
