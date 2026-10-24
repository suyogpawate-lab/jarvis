"""Local mission memory: inspect prior JARVIS tasks without extra model calls.

This module reads the TaskExecutor's persisted JSON records. It never executes,
retries, or resumes actions; its output is diagnostic evidence, not a guarantee.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


_TASK_ID = re.compile(r"^task-[0-9a-f]{8}$")
_SECRET = re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)(\s*[:=]\s*)[^\s,;]+")


def _clean(value, limit=220):
    text = str(value or "").replace("\n", " ").strip()
    text = _SECRET.sub(r"\1\2[REDACTED]", text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _timestamp(task):
    """Sort malformed/legacy records safely instead of breaking all insights."""
    try:
        return float(task.get("updated_at") or task.get("created_at") or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


class MissionInsights:
    """Search task history and surface repeated outcomes using local data only."""

    def __init__(self, task_dir):
        self.task_dir = Path(task_dir)

    def _records(self):
        records = []
        if not self.task_dir.exists():
            return records
        for path in self.task_dir.glob("task-????????.json"):
            if not _TASK_ID.fullmatch(path.stem):
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(item, dict) and item.get("id") == path.stem:
                records.append(item)
        return sorted(records, key=_timestamp, reverse=True)

    @staticmethod
    def _steps(task):
        steps = task.get("steps", [])
        return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []

    def insights(self):
        records = self._records()
        if not records:
            return "JARVIS Mission Memory: no saved tasks yet. Run a multi-step /agent task to begin building local history."
        counts = Counter(str(item.get("status", "UNKNOWN")) for item in records)
        completed = counts.get("COMPLETED", 0)
        failed = counts.get("FAILED", 0)
        known = completed + failed
        lines = [
            "JARVIS Mission Memory",
            f"Saved tasks: {len(records)} | completed: {completed} | failed: {failed} | other/interrupted: {len(records) - known}",
        ]
        if known:
            lines.append(f"Observed completion rate (completed + failed only): {completed / known:.0%}")
        failures = Counter()
        for task in records:
            if task.get("status") != "FAILED":
                continue
            for step in self._steps(task):
                if step.get("status") == "FAILED":
                    signature = _clean(step.get("command"), 100)
                    if signature:
                        failures[signature] += 1
                    break
        if failures:
            lines.append("Most repeated failing first steps:")
            for command, amount in failures.most_common(3):
                lines.append(f"  {amount}× {command}")
            lines.append("These are historical patterns, not proof of the current root cause.")
        recent = [item for item in records if item.get("status") in {"PAUSED_RECOVERY", "WAITING_APPROVAL"}]
        if recent:
            lines.append(f"Tasks needing attention: {len(recent)} (inspect with /agent diagnose <task-id>).")
        lines.append("All analysis is local; no model/API request was made.")
        return "\n".join(lines)

    def diagnose(self, task_id):
        task_id = str(task_id or "").strip()
        if not _TASK_ID.fullmatch(task_id):
            return "[ERROR] Invalid task ID."
        path = self.task_dir / (task_id + ".json")
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return f"[ERROR] Task not found: {task_id}"
        except (OSError, ValueError, json.JSONDecodeError):
            return f"[ERROR] Task record is unreadable: {task_id}"
        if not isinstance(task, dict) or task.get("id") != task_id:
            return f"[ERROR] Task record has an invalid format: {task_id}"
        steps = self._steps(task)
        lines = [
            f"Mission diagnosis: {task_id}",
            f"Goal: {_clean(task.get('goal'), 300) or '(not recorded)'}",
            f"Status: {_clean(task.get('status'), 50) or 'UNKNOWN'}",
            f"Progress: {sum(s.get('status') == 'COMPLETED' for s in steps)}/{len(steps)} steps completed",
        ]
        failure = _clean(task.get("failure"), 300)
        if failure:
            lines.append(f"Recorded issue: {failure}")
        for step in steps:
            status = str(step.get("status") or "UNKNOWN")
            if status in {"FAILED", "WAITING_APPROVAL", "PENDING", "RUNNING"}:
                lines.append(f"Step {step.get('number', '?')} [{status}]: {_clean(step.get('command'), 180)}")
                result = _clean(step.get("result"), 300)
                if result:
                    lines.append(f"  Result: {result}")
                if status == "FAILED":
                    lines.append("  Next: inspect this command/result and correct the cause before creating a new attempt.")
                    break
                if status == "RUNNING":
                    lines.append("  Caution: completion may be unknown; do not blindly repeat side-effecting actions.")
                    break
        if task.get("status") == "COMPLETED":
            lines.append("Outcome: executor marked the workflow completed; this does not independently verify external side effects.")
        elif task.get("status") == "FAILED":
            lines.append("Outcome: remaining steps were stopped after failure.")
        elif task.get("status") == "PAUSED_RECOVERY":
            lines.append("Outcome: process interruption was detected; check whether the last action happened before rerunning.")
        else:
            lines.append("Outcome: inspect the step states above; no action was executed by this diagnosis.")
        return "\n".join(lines)

    def recall(self, query, limit=5):
        query = " ".join(str(query or "").split()).lower()
        if not query:
            return "Usage: /agent recall <words to search in saved task history>"
        if len(query) > 300:
            return "[ERROR] Search query is limited to 300 characters."
        terms = [term for term in re.findall(r"[a-z0-9_-]+", query) if len(term) > 1]
        if not terms:
            return "[ERROR] Provide at least one searchable word."
        matches = []
        for task in self._records():
            fields = [str(task.get("goal") or "")]
            for step in self._steps(task):
                fields.extend([str(step.get("command") or ""), str(step.get("result") or "")])
            haystack = " ".join(fields).lower()
            score = sum(haystack.count(term) for term in set(terms))
            if score:
                matches.append((score, task))
        matches.sort(key=lambda pair: (pair[0], _timestamp(pair[1])), reverse=True)
        if not matches:
            return "No matching saved missions found. Search is local and does not call an AI provider."
        lines = [f"Local mission recall: {len(matches)} match(es), showing up to {min(limit, len(matches))}"]
        for score, task in matches[:limit]:
            lines.append(f"- {task.get('id')} [{task.get('status', 'UNKNOWN')}] score={score}: {_clean(task.get('goal'), 180)}")
            for step in self._steps(task):
                if any(term in str(step.get("command") or "").lower() for term in terms):
                    lines.append(f"  Step {step.get('number', '?')} [{step.get('status', 'UNKNOWN')}]: {_clean(step.get('command'), 160)}")
                    break
        lines.append("Recall reports past records only; it does not rerun a workflow.")
        return "\n".join(lines)
