"""Lightweight local task-outcome and duration predictor.

Uses only completed/failed TaskExecutor records. It is a transparent Naive Bayes
baseline, not an LLM confidence claim. No history leaves the device.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import median

_TASK_ID = re.compile(r"^task-[0-9a-f]{8}$")
_TOKEN = re.compile(r"[a-z0-9_+-]{2,}")
_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "then", "into",
    "your", "you", "jarvis", "please", "task", "step", "run", "use", "via",
    "are", "was", "were", "will", "can", "could", "should", "would",
}


class MissionPredictor:
    def __init__(self, task_dir):
        self.task_dir = Path(task_dir)

    @staticmethod
    def _features(task):
        text = str(task.get("goal") or "")
        steps = task.get("steps") or []
        if isinstance(steps, list):
            text += " " + " ".join(
                str(step.get("command") or "")
                for step in steps if isinstance(step, dict)
            )
        return set(token for token in _TOKEN.findall(text.lower()) if token not in _STOP)

    @staticmethod
    def _duration(task):
        steps = task.get("steps") or []
        durations = []
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                try:
                    start, end = float(step.get("started_at")), float(step.get("finished_at"))
                    if end >= start > 0:
                        durations.append(end - start)
                except (TypeError, ValueError, OverflowError):
                    continue
        return sum(durations) if durations else None

    def _records(self):
        records = []
        if not self.task_dir.is_dir():
            return records
        for path in self.task_dir.glob("task-????????.json"):
            if not _TASK_ID.fullmatch(path.stem):
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(item, dict) and item.get("id") == path.stem:
                if item.get("status") in {"COMPLETED", "FAILED"}:
                    records.append(item)
        return records

    def predict(self, goal):
        goal = " ".join(str(goal or "").split())
        if not goal:
            return "Usage: /agent predict <goal>"
        records = self._records()
        successes = [r for r in records if r.get("status") == "COMPLETED"]
        failures = [r for r in records if r.get("status") == "FAILED"]
        total = len(successes) + len(failures)
        if total < 5 or len(successes) < 2 or len(failures) < 2:
            return (
                "[PREDICTION] Not enough local outcomes yet. "
                f"Completed={len(successes)}, failed={len(failures)}; "
                "need at least 5 resolved tasks and 2 in each class. "
                "No prediction was fabricated."
            )

        documents = [(self._features(r), 1) for r in successes]
        documents += [(self._features(r), 0) for r in failures]
        vocabulary = set().union(*(features for features, _ in documents))
        query = self._features({"goal": goal})
        prior = math.log((len(successes) + 1) / (len(failures) + 1))
        score = prior
        for token in query & vocabulary:
            positive = sum(token in features for features, label in documents if label == 1)
            negative = sum(token in features for features, label in documents if label == 0)
            p_pos = (positive + 1) / (len(successes) + 2)
            p_neg = (negative + 1) / (len(failures) + 2)
            score += math.log(p_pos / p_neg)
        probability = 1 / (1 + math.exp(-max(-30, min(30, score))))

        similarities = []
        for task in successes:
            features = self._features(task)
            union = query | features
            overlap = len(query & features) / len(union) if union else 0.0
            duration = self._duration(task)
            if duration is not None and overlap > 0:
                similarities.append((overlap, duration))
        similarities.sort(reverse=True)
        estimate = None
        if len(similarities) >= 3:
            estimate = median(value for _, value in similarities[:5])

        lines = [
            "[PREDICTION] Local historical estimate",
            f"Estimated completion likelihood: {probability:.0%}",
            f"Training history: {len(successes)} completed / {len(failures)} failed tasks",
            "Method: Laplace-smoothed Naive Bayes over local task text; not a guarantee.",
        ]
        if estimate is not None:
            lines.append(f"Estimated active execution time: {estimate:.0f}s (median of similar completed tasks).")
        else:
            lines.append("Execution-time estimate: unavailable (fewer than 3 similar timed tasks).")
        lines.append("This estimate is based on JARVIS's local task history only.")
        return "\n".join(lines)
