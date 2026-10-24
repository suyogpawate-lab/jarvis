"""Tests for the bounded Agent Engine and proactive health monitor."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.agent_engine import AgentEngine
from automation.task_executor import TaskExecutor
from monitoring.health_manager import HealthManager


class FakeGemini:
    gemini_api_keys = ["configured"]

    def _gemini_request(self, messages, **kwargs):
        return json.dumps({
            "goal": "test workflow",
            "steps": [
                {"title": "Inspect", "action": "report project status"},
                {"title": "Validate", "action": "run unit tests"},
            ],
        })


class AgentEngineTests(unittest.TestCase):
    def test_plan_is_persisted_but_not_executed_until_run(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            executor = TaskExecutor(lambda step: calls.append(step) or "[OK] complete", task_dir=directory)
            engine = AgentEngine(FakeGemini(), executor)
            result = engine.handle("/agent plan test workflow")
            self.assertIn("[AGENT PLAN]", result)
            self.assertEqual(calls, [])
            self.assertIn("Review the steps", result)

    def test_run_uses_existing_dispatcher_and_completes_steps(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            executor = TaskExecutor(lambda step: calls.append(step) or "[OK] complete", task_dir=directory)
            engine = AgentEngine(FakeGemini(), executor)
            planned = engine.handle("/agent plan test workflow")
            import re
            task_id = re.search(r"task-[0-9a-f]{8}", planned).group(0)
            result = engine.handle(f"/agent run {task_id}", source="text")
            self.assertIn("COMPLETED", result)
            self.assertEqual(len(calls), 2)

    def test_execute_goal_plans_and_runs_without_user_task_id(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            executor = TaskExecutor(lambda step: calls.append(step) or "[OK] complete", task_dir=directory)
            engine = AgentEngine(FakeGemini(), executor)
            result = engine.execute_goal("inspect project and run tests", source="text")
            self.assertIn("[AGENT TASK]", result)
            self.assertIn("COMPLETED", result)
            self.assertEqual(len(calls), 2)

    def test_missing_gemini_is_reported_without_execution(self):
        class NoGemini:
            gemini_api_keys = []
        with tempfile.TemporaryDirectory() as directory:
            executor = TaskExecutor(lambda step: self.fail("must not dispatch"), task_dir=directory)
            engine = AgentEngine(NoGemini(), executor)
            self.assertIn("Gemini is not configured", engine.handle("/agent plan build something"))

    def test_interrupted_running_task_is_paused_for_review(self):
        with tempfile.TemporaryDirectory() as directory:
            executor = TaskExecutor(lambda step: "[OK]", task_dir=directory)
            created = executor.create(["first step", "second step"])
            import re
            task_id = re.search(r"task-[0-9a-f]{8}", created).group(0)
            path = Path(directory) / f"{task_id}.json"
            task = json.loads(path.read_text())
            task["status"] = "RUNNING"
            task["current_step"] = 1
            task["steps"][0]["status"] = "COMPLETED"
            task["steps"][1]["status"] = "RUNNING"
            path.write_text(json.dumps(task))
            recovered = executor.recover_interrupted()
            self.assertEqual(recovered, [task_id])
            saved = json.loads(path.read_text())
            self.assertEqual(saved["status"], "PAUSED_RECOVERY")
            self.assertEqual(saved["steps"][0]["status"], "COMPLETED")
            self.assertEqual(saved["steps"][1]["status"], "PENDING")
            self.assertIn("not automatically repeated", saved["steps"][1]["result"])


    def test_dispatcher_routes_agent_and_health_before_ai(self):
        from automation.command_dispatcher import CommandDispatcher
        dispatcher = object.__new__(CommandDispatcher)
        dispatcher.agent_engine = type("Agent", (), {"handle": lambda self, text, source="external": "agent-routed"})()
        dispatcher.health_manager = type("Health", (), {"report": lambda self: "health-routed"})()
        self.assertEqual(dispatcher.dispatch("/agent help"), "agent-routed")
        self.assertEqual(dispatcher.dispatch("/health"), "health-routed")

    def test_natural_language_action_routes_to_agent_immediately(self):
        dispatcher = object.__new__(CommandDispatcher)
        dispatcher.agent_engine = type("Agent", (), {
            "execute_goal": lambda self, goal, source="external": f"executed:{goal}"
        })()
        self.assertTrue(dispatcher._looks_like_agent_task("please fix the project tests"))
        self.assertTrue(dispatcher._looks_like_agent_task("Build a CLI tool"))
        self.assertFalse(dispatcher._looks_like_agent_task("How do I fix a test?"))
        self.assertFalse(dispatcher._looks_like_agent_task("What should I build?"))


class HealthManagerTests(unittest.TestCase):
    @patch("monitoring.health_manager.get_telemetry")
    @patch.object(HealthManager, "_reachable", return_value=True)
    def test_health_report_is_read_only_and_includes_metrics(self, _reachable, telemetry):
        telemetry.return_value = {
            "cpu": {"percent": 15},
            "memory": {"percent": 40, "available": 1024 ** 3, "swap_percent": 5},
        }
        manager = HealthManager(interval=60)
        with patch("monitoring.health_manager.shutil.disk_usage") as disk:
            disk.return_value = type("Usage", (), {"free": 5 * 1024 ** 3})()
            report = manager.report()
        self.assertIn("JARVIS proactive health report", report)
        self.assertIn("CPU: 15.0%", report)
        self.assertIn("No services were restarted", report)


if __name__ == "__main__":
    unittest.main()
