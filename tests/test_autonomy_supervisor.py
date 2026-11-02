import json
import tempfile
import unittest
from pathlib import Path

from automation.autonomy_supervisor import AutonomySupervisor


class AutonomySupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state.json"
        self.executed = []

    def supervisor(self, decide):
        return AutonomySupervisor(
            decide=decide,
            execute=lambda action: self.executed.append(action) or "[OK] verified",
            state_path=self.state,
            interval=0.5,
        )

    def test_ingest_persists_and_deduplicates_event_ids(self):
        supervisor = self.supervisor(lambda event: [])
        first = supervisor.ingest("notification", "battery low", event_id="evt-1")
        duplicate = supervisor.ingest("notification", "battery low", event_id="evt-1")

        self.assertTrue(first["accepted"])
        self.assertTrue(duplicate["duplicate"])
        saved = json.loads(self.state.read_text())
        self.assertEqual(len(saved["events"]), 1)
        self.assertEqual(saved["events"][0]["status"], "PENDING")

    def test_safe_mission_is_executed_and_verified(self):
        supervisor = self.supervisor(
            lambda event: [{"action": "inspect service status", "risk": "read_only"}]
        )
        supervisor.ingest("health", "service check failed", event_id="evt-2")

        result = supervisor.tick()

        self.assertEqual(result["assessment"]["missions_created"], 1)
        self.assertEqual(result["execution"]["status"], "COMPLETED")
        self.assertEqual(self.executed, ["inspect service status"])
        self.assertEqual(supervisor.status()["completed_missions"], 1)

    def test_unknown_risk_waits_for_approval(self):
        supervisor = self.supervisor(
            lambda event: [{"action": "send a message", "risk": "unknown"}]
        )
        supervisor.ingest("event", "new message", event_id="evt-3")

        result = supervisor.tick()

        self.assertFalse(result["execution"]["executed"])
        self.assertEqual(supervisor.status()["waiting_approval"], 1)
        self.assertEqual(self.executed, [])

    def test_approval_is_explicit_and_one_time(self):
        supervisor = self.supervisor(
            lambda event: [{"action": "perform approved action", "risk": "sensitive"}]
        )
        supervisor.ingest("event", "requested action", event_id="evt-4")
        supervisor.process_once()
        mission_id = supervisor.status()["recent_missions"][0]["id"]

        self.assertTrue(supervisor.approve(mission_id)["ok"])
        self.assertEqual(supervisor.tick()["execution"]["status"], "COMPLETED")
        self.assertFalse(supervisor.approve(mission_id)["ok"])

    def test_interrupted_running_mission_is_not_replayed(self):
        supervisor = self.supervisor(lambda event: [])
        supervisor._state["missions"].append({
            "id": "mission-interrupted",
            "event_id": "evt-5",
            "action": "possibly already performed",
            "risk": "safe",
            "status": "RUNNING",
        })
        supervisor._save()

        recovered = self.supervisor(lambda event: [])

        self.assertEqual(recovered.status()["paused_missions"], 1)
        self.assertFalse(recovered.execute_once()["executed"])
        self.assertEqual(self.executed, [])

    def test_decision_failure_is_persisted(self):
        supervisor = self.supervisor(lambda event: (_ for _ in ()).throw(RuntimeError("planner offline")))
        supervisor.ingest("scheduler", "scheduled check", event_id="evt-6")

        result = supervisor.process_once()

        self.assertIn("planner offline", result["error"])
        saved = json.loads(self.state.read_text())
        self.assertEqual(saved["events"][0]["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
