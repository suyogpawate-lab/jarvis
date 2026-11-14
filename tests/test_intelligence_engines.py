"""Tests for local intelligence and adapter-promotion safeguards."""
import json
import tempfile
import unittest
from pathlib import Path

from intelligence.forecast_engine import ForecastEngine
from intelligence.vision_engine import VisionEngine
from intelligence.model_evaluation import ModelEvaluation


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_forecast_baseline_is_bounded_and_finite(self):
        result = ForecastEngine().forecast([10, 11, 12, 13], 3)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["forecast"]), 3)
        self.assertEqual(result["model"], "damped_median_trend")

    def test_forecast_rejects_insufficient_history(self):
        self.assertFalse(ForecastEngine().forecast([1, 2])["ok"])

    def test_vision_fails_closed_when_weights_are_missing(self):
        engine = VisionEngine(self.root / "missing.onnx", self.root / "missing.json")
        result = engine.classify(self.root / "screen.png")
        self.assertFalse(result["ok"])
        self.assertEqual(result["labels"], [])

    def test_candidate_adapter_is_rejected_on_accuracy_regression(self):
        baseline = {"task_accuracy": .95, "instruction_following": .94, "safety_pass_rate": .99}
        candidate = {"task_accuracy": .90, "instruction_following": .94, "safety_pass_rate": .99}
        base_path, candidate_path = self.root / "base.json", self.root / "candidate.json"
        base_path.write_text(json.dumps(baseline), encoding="utf-8")
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        result = ModelEvaluation(base_path, candidate_path).compare()
        self.assertFalse(result["promote"])
        self.assertIn("task_accuracy", result["regressions"])

    def test_candidate_within_regression_budget_can_pass(self):
        metrics = {"task_accuracy": .95, "instruction_following": .94, "safety_pass_rate": .99}
        base_path, candidate_path = self.root / "base.json", self.root / "candidate.json"
        base_path.write_text(json.dumps(metrics), encoding="utf-8")
        candidate = dict(metrics, task_accuracy=.945)
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        self.assertTrue(ModelEvaluation(base_path, candidate_path).compare()["promote"])


if __name__ == "__main__":
    unittest.main()
