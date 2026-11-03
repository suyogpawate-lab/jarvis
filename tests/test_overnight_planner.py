import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from automation.overnight_planner import OvernightPlanner


class OvernightPlannerTests(unittest.TestCase):
    def test_plan_is_bounded_and_never_executes_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Mock()
            agent.ask.return_value = json.dumps({
                "suggestions": [
                    "Review service health tomorrow.",
                    "Inspect failed diagnostics.",
                    "Review pending approvals.",
                    "This fourth suggestion must be dropped.",
                ]
            })
            autonomy = Mock()
            autonomy.status.return_value = {
                "pending_events": 1,
                "failed_missions": 2,
                "recent_missions": [{"description": "private message body"}],
            }
            planner = OvernightPlanner(
                agent, autonomy, state_path=Path(directory) / "plan.json",
                run_hour=3, run_minute=0,
            )
            record = planner.run_once()
            self.assertEqual(len(record["suggestions"]), 3)
            self.assertFalse(record["execution_performed"])
            saved = json.loads((Path(directory) / "plan.json").read_text())
            self.assertEqual(saved["status"], "READY_FOR_OWNER_REVIEW")
            prompt = agent.ask.call_args.args[0]
            self.assertNotIn("private message body", prompt)

    def test_invalid_model_output_creates_empty_review_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Mock()
            agent.ask.return_value = "not json"
            autonomy = Mock()
            autonomy.status.return_value = {}
            planner = OvernightPlanner(agent, autonomy, state_path=Path(directory) / "plan.json")
            record = planner.run_once()
            self.assertEqual(record["suggestions"], [])
            self.assertFalse(record["execution_performed"])

    def test_invalid_schedule_time_is_rejected(self):
        with self.assertRaises(ValueError):
            OvernightPlanner(Mock(), Mock(), run_hour=25, run_minute=0)


if __name__ == "__main__":
    unittest.main()
