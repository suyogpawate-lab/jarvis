"""Tests for local task-outcome and duration prediction."""
import json
import tempfile
import unittest
from pathlib import Path

from automation.mission_predictor import MissionPredictor


class MissionPredictorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.predictor = MissionPredictor(self.root)

    def add_task(self, index, status, goal, duration):
        task = {
            "id": f"task-{index:08x}",
            "status": status,
            "goal": goal,
            "steps": [{
                "command": goal,
                "started_at": 100.0,
                "finished_at": 100.0 + duration,
            }],
        }
        (self.root / f"{task['id']}.json").write_text(
            json.dumps(task), encoding="utf-8"
        )

    def test_insufficient_history_is_reported_instead_of_guessing(self):
        self.add_task(1, "COMPLETED", "debug python android", 5)
        result = self.predictor.predict("debug python android")
        self.assertIn("Not enough local outcomes", result)

    def test_predicts_from_local_completed_and_failed_history(self):
        for index in range(1, 4):
            self.add_task(index, "COMPLETED", "debug python android", 5)
        for index in range(4, 6):
            self.add_task(index, "FAILED", "build game server", 12)
        result = self.predictor.predict("debug python android")
        self.assertIn("Estimated completion likelihood:", result)
        self.assertIn("3 completed / 2 failed", result)
        self.assertIn("Estimated active execution time: 5s", result)
        self.assertIn("not a guarantee", result)


if __name__ == "__main__":
    unittest.main()
