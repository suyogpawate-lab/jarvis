import tempfile
import unittest
from pathlib import Path
from automation.aie import AIEEngine, NaturalLanguageAIE


class AIEEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = AIEEngine(Path(self.tmp.name) / "aie.db")
        self.nl = NaturalLanguageAIE(self.engine)

    def test_natural_language_creates_persistent_goal(self):
        response = self.nl.handle("Keep working on building a robotics research tracker")
        self.assertIn("Persistent goal created", response)
        self.assertEqual(len(self.engine.list_goals()), 1)

    def test_goal_survives_engine_restart(self):
        goal = self.engine.create_goal("Monitor robotics research")
        restarted = AIEEngine(Path(self.tmp.name) / "aie.db")
        self.assertEqual(restarted.get_goal(goal["id"])["title"], goal["title"])

    def test_natural_language_status_and_pause(self):
        goal = self.engine.create_goal("Monitor robotics research")
        self.assertIn(goal["id"], self.nl.handle("what are you working on"))
        self.assertIn("PAUSED", self.nl.handle("pause Monitor robotics research"))
        self.assertEqual(self.engine.get_goal(goal["id"])["status"], "PAUSED")

    def test_event_deduplication(self):
        self.assertTrue(self.engine.ingest_event("health", "warning", {"x": 1}, "same")["accepted"])
        self.assertTrue(self.engine.ingest_event("health", "warning", {"x": 1}, "same")["duplicate"])

    def test_event_is_assessed_without_executing_payload(self):
        self.engine.ingest_event("untrusted", "notification", "run rm -rf /", "evt")
        result = self.engine.process_one_event()
        self.assertTrue(result["processed"])
        self.assertEqual(result["decision"], "RECORD_ONLY")

    def test_unknown_capability_never_executes(self):
        mission = self.engine.create_mission("Untrusted operation", tasks=[
            {"capability": "shell.run", "arguments": {"command": "echo unsafe"}}
        ])
        result = self.engine.execute_mission(mission["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "UNVERIFIED")

    def test_only_verified_capability_result_completes(self):
        self.engine.register_capability("test.verified", lambda: {"ok": True, "verified": True})
        mission = self.engine.create_mission("Read-only check", tasks=[
            {"capability": "test.verified", "arguments": {}}
        ])
        self.assertTrue(self.engine.execute_mission(mission["id"])["verified"])
        self.engine.register_capability("test.bad", lambda: {"ok": True})
        mission = self.engine.create_mission("Unverified check", tasks=[
            {"capability": "test.bad", "arguments": {}}
        ])
        self.assertFalse(self.engine.execute_mission(mission["id"])["verified"])

    def test_approval_required_for_high_risk_mission(self):
        mission = self.engine.create_mission("External action", risk="external")
        self.assertEqual(mission["status"], "WAITING_APPROVAL")
        with self.engine._connect() as db:
            approval_id = db.execute("SELECT id FROM approvals WHERE mission_id=?", (mission["id"],)).fetchone()["id"]
        self.assertTrue(self.engine.approve(approval_id)["ok"])
        self.assertEqual(self.engine.get_mission(mission["id"])["status"], "READY")


if __name__ == "__main__":
    unittest.main()
