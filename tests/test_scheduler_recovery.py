import json
import tempfile
import time
import unittest
from pathlib import Path
from automation.scheduler import AutomationScheduler

class SchedulerRecoveryTests(unittest.TestCase):
    def test_interrupted_running_job_is_paused_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auto-interrupted.json"
            path.write_text(json.dumps({"id":"auto-interrupted","command":"research x",
                "status":"RUNNING","next_run":time.time()-10}), encoding="utf-8")
            called = []
            scheduler = AutomationScheduler(lambda command: called.append(command), base_dir=directory)
            try:
                job = scheduler.get("auto-interrupted")
                self.assertEqual(job["status"], "PAUSED_RECOVERY")
                self.assertIn("not automatically replayed", job["recovery_note"])
                self.assertEqual(called, [])
            finally:
                scheduler.shutdown()

    def test_recovered_job_requires_explicit_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auto-recovered.json"
            path.write_text(json.dumps({"id":"auto-recovered","command":"research x",
                "status":"RUNNING","next_run":time.time()-10}), encoding="utf-8")
            called = []
            scheduler = AutomationScheduler(lambda command: called.append(command) or "done", base_dir=directory)
            try:
                result = scheduler.resume_recovered("auto-recovered")
                self.assertEqual(result["status"], "SCHEDULED")
                deadline = time.time() + 3
                while time.time() < deadline and not called:
                    time.sleep(0.05)
                self.assertEqual(called, ["research x"])
                self.assertEqual(scheduler.get("auto-recovered")["status"], "DONE")
            finally:
                scheduler.shutdown()

    def test_reschedule_preserves_task_identity_and_command(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        with tempfile.TemporaryDirectory() as directory:
            scheduler = AutomationScheduler(
                lambda command: "done", base_dir=directory, timezone="Asia/Kolkata"
            )
            try:
                original = scheduler.schedule(
                    "research autonomous Android reliability",
                    time.time() + 3600,
                    description="Overnight research",
                )
                created_at = original["created_at"]
                command = original["command"]
                new_run = time.time() + 7200
                updated = scheduler.reschedule(original["id"], new_run)
                self.assertEqual(updated["status"], "SCHEDULED")
                self.assertEqual(updated["command"], command)
                self.assertEqual(updated["description"], "Overnight research")
                self.assertEqual(updated["created_at"], created_at)
                self.assertEqual(updated["run_at"], new_run)
                self.assertEqual(updated["next_run"], new_run)
            finally:
                scheduler.shutdown()

    def test_reschedule_rejects_completed_or_past_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            scheduler = AutomationScheduler(lambda command: "done", base_dir=directory)
            try:
                item = scheduler.schedule("noop", time.time() + 3600)
                item["status"] = "DONE"
                scheduler._save(item)
                result = scheduler.reschedule(item["id"], time.time() + 7200)
                self.assertIn("Only SCHEDULED", result["error"])
                result = scheduler.reschedule("missing-auto", time.time() + 7200)
                self.assertIn("Unknown automation", result["error"])
                result = scheduler.reschedule(item["id"], time.time() - 1)
                self.assertIn("future", result["error"])
            finally:
                scheduler.shutdown()

    def test_weekly_repeat_uses_local_calendar_days(self):
        from zoneinfo import ZoneInfo
        from datetime import datetime
        with tempfile.TemporaryDirectory() as directory:
            scheduler = AutomationScheduler(lambda command: "done", base_dir=directory,
                                            timezone="America/New_York")
            try:
                scheduled = datetime(2026, 3, 1, 9, 0, tzinfo=ZoneInfo("America/New_York"))
                automation = {"repeat_mode": "weekly", "next_run": scheduled.timestamp()}
                next_run = scheduler._next_repeat_time(automation, now=scheduled.timestamp())
                local = datetime.fromtimestamp(next_run, ZoneInfo("America/New_York"))
                self.assertEqual((local.hour, local.minute), (9, 0))
                self.assertEqual((local - scheduled).days, 7)
            finally:
                scheduler.shutdown()

    def test_running_state_is_persisted_before_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            observed = []
            scheduler = None
            def callback(command):
                observed.append(scheduler.get(job["id"])["status"])
                return "done"
            scheduler = AutomationScheduler(callback, base_dir=directory)
            try:
                job = scheduler.schedule("noop", time.time()+3600)
                scheduler._execute(job)
                self.assertEqual(observed, ["RUNNING"])
                self.assertEqual(scheduler.get(job["id"])["status"], "DONE")
            finally:
                scheduler.shutdown()

if __name__ == "__main__":
    unittest.main()
