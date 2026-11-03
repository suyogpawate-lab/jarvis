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


    def test_configured_research_is_bounded_and_saved_for_review(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Mock()
            agent.ask.return_value = json.dumps({"suggestions": []})
            autonomy = Mock()
            autonomy.status.return_value = {}
            research = Mock()
            research.search.side_effect = [
                "Evidence summary for physics.",
                "Evidence summary for robotics.",
                "Evidence summary for chemistry.",
            ]
            planner = OvernightPlanner(
                agent, autonomy, deep_search=research,
                state_path=Path(directory) / "plan.json",
                research_topics=[
                    "physics topic", "robotics topic", "chemistry topic",
                    "fourth topic must be ignored",
                ],
            )
            record = planner.run_once()
            self.assertEqual(len(record["research"]), 3)
            self.assertEqual(research.search.call_count, 3)
            self.assertEqual(record["research"][0]["topic"], "physics topic")
            self.assertFalse(record["execution_performed"])
            saved = json.loads((Path(directory) / "plan.json").read_text())
            self.assertEqual(len(saved["research"]), 3)

    def test_research_failure_is_recorded_without_stopping_other_topics(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Mock()
            agent.ask.return_value = '{"suggestions":[]}'
            autonomy = Mock()
            autonomy.status.return_value = {}
            research = Mock()
            research.search.side_effect = [RuntimeError("network unavailable"), "usable evidence"]
            planner = OvernightPlanner(
                agent, autonomy, deep_search=research,
                state_path=Path(directory) / "plan.json",
                research_topics=["topic one", "topic two"],
            )
            record = planner.run_once()
            self.assertEqual(record["research"][0]["status"], "FAILED")
            self.assertEqual(record["research"][1]["status"], "COMPLETED")

    def test_topics_are_deduplicated_and_capped(self):
        with tempfile.TemporaryDirectory() as directory:
            planner = OvernightPlanner(
                Mock(), Mock(), state_path=Path(directory) / "plan.json",
                research_topics=["same", "same", "two", "three", "four"],
            )
            self.assertEqual(planner.research_topics, ["same", "two", "three"])

    def test_invalid_schedule_time_is_rejected(self):
        with self.assertRaises(ValueError):
            OvernightPlanner(Mock(), Mock(), run_hour=25, run_minute=0)


if __name__ == "__main__":
    unittest.main()
