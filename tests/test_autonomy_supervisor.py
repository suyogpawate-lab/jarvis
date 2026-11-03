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
            execute=lambda action: self.executed.append(action) or {"ok": True, "verified": True, "operation": action},
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
            lambda event: [{"action": "health_snapshot", "risk": "read_only"}]
        )
        supervisor.ingest("health", "service check failed", event_id="evt-2")

        result = supervisor.tick()

        self.assertEqual(result["assessment"]["missions_created"], 1)
        self.assertEqual(result["execution"]["status"], "COMPLETED")
        self.assertEqual(self.executed, ["health_snapshot"])
        self.assertEqual(supervisor.status()["completed_missions"], 1)

    def test_unknown_risk_is_blocked_without_approval_path(self):
        supervisor = self.supervisor(
            lambda event: [{"action": "send a message", "risk": "unknown"}]
        )
        supervisor.ingest("event", "new message", event_id="evt-3")

        result = supervisor.tick()

        self.assertFalse(result["execution"]["executed"])
        self.assertEqual(supervisor.status()["blocked_missions"], 1)
        self.assertEqual(self.executed, [])

    def test_approval_is_explicit_and_one_time(self):
        supervisor = self.supervisor(
            lambda event: [{"action": "android_back", "risk": "sensitive"}]
        )
        supervisor.ingest("event", "requested action", event_id="evt-4")
        supervisor.process_once()
        mission_id = supervisor.status()["recent_missions"][0]["id"]

        self.assertTrue(supervisor.approve(mission_id)["ok"])
        execution = supervisor.execute_once()
        self.assertFalse(execution["executed"])
        self.assertEqual(execution["status"], "COMPLETED")
        self.assertEqual(supervisor.status()["completed_missions"], 1)
        self.assertEqual(self.executed, ["android_back"])
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

    def test_shell_and_misleading_prefixes_are_not_allowlisted(self):
        from automation.autonomy_supervisor import _policy_risk
        dangerous = [
            "ls; rm -rf /",
            "show status && touch /tmp/pwned",
            "inspect $(id)",
            "check \`id\`",
            "git status | sh",
            "read /etc/passwd > /tmp/out",
            "python -c 'print(1)'",
            "health_snapshot; rm -rf /",
            "show me how to send a message",
        ]
        for action in dangerous:
            with self.subTest(action=action):
                self.assertIn(_policy_risk(action), {"approval_required", "blocked"})
        self.assertEqual(_policy_risk("health_snapshot"), "read_only")
        self.assertEqual(_policy_risk("android_back"), "approval_required")
        self.assertEqual(_policy_risk("android_tap:1:2"), "blocked")

    def test_unverified_executor_result_is_not_completed(self):
        supervisor = AutonomySupervisor(
            decide=lambda event: [{"action": "health_snapshot"}],
            execute=lambda action: "[OK] maybe",
            state_path=self.state,
            interval=0.5,
        )
        supervisor.ingest("health", "warning", event_id="evt-unverified")
        result = supervisor.tick()
        self.assertEqual(result["execution"]["status"], "UNVERIFIED")
        self.assertEqual(supervisor.status()["unverified_missions"], 1)
        self.assertEqual(supervisor.status()["completed_missions"], 0)

    def test_start_is_idempotent_and_stop_joins_thread(self):
        supervisor = self.supervisor(lambda event: [])
        self.assertTrue(supervisor.start())
        self.assertFalse(supervisor.start())
        thread = supervisor._thread
        supervisor.stop(timeout=2)
        supervisor.stop(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_unknown_action_cannot_be_approved_into_execution(self):
        supervisor = self.supervisor(
            lambda event: [{"action": "run arbitrary command"}]
        )
        supervisor.ingest("event", "request", event_id="evt-unknown-approval")
        supervisor.process_once()
        mission_id = supervisor.status()["recent_missions"][0]["id"]
        result = supervisor.approve(mission_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "mission_not_waiting_for_approval")
        self.assertEqual(supervisor.status()["blocked_missions"], 1)
        self.assertEqual(self.executed, [])

    def test_model_risk_label_cannot_downgrade_mutating_action(self):
        supervisor = self.supervisor(
            lambda event: [{"action": "send a WhatsApp message", "risk": "read_only"}]
        )
        supervisor.ingest("event", "untrusted request", event_id="evt-risk-downgrade")
        supervisor.process_once()
        self.assertEqual(supervisor.status()["blocked_missions"], 1)
        self.assertEqual(self.executed, [])

    def test_exact_allowlisted_operation_ignores_model_risk_label(self):
        supervisor = self.supervisor(
            lambda event: [{"action": "health_snapshot", "risk": "approval_required"}]
        )
        supervisor.ingest("health", "warning", event_id="evt-safe-risk-label")
        result = supervisor.tick()
        self.assertEqual(result["execution"]["status"], "COMPLETED")
        self.assertEqual(self.executed, ["health_snapshot"])


if __name__ == "__main__":
    unittest.main()
