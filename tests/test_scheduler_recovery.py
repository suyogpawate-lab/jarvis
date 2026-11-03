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
