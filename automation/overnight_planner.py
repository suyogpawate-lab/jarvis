"""Bounded overnight planning and configured-topic research for JARVIS.

The daily planner runs by default but can be disabled with
JARVIS_OVERNIGHT_PLANNING=0. It uses aggregate autonomy counters only for
planning suggestions. Optional research is restricted to owner-configured
topics, bounded to three queries, and saved for owner review. It never
executes tasks or performs external side effects.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


MAX_SUGGESTIONS = 3
MAX_RESEARCH_TOPICS = 3
MAX_TOPIC_LENGTH = 240
MAX_RESEARCH_CHARS = 3000


def _configured_topics(raw: str | None = None) -> list[str]:
    """Parse a small, explicit owner-maintained research queue."""
    value = os.getenv("JARVIS_OVERNIGHT_RESEARCH_TOPICS", "") if raw is None else raw
    topics = []
    for item in str(value or "").replace("\n", ",").split(","):
        topic = " ".join(item.split())[:MAX_TOPIC_LENGTH]
        if topic and topic not in topics:
            topics.append(topic)
        if len(topics) >= MAX_RESEARCH_TOPICS:
            break
    return topics


class OvernightPlanner:
    def __init__(
        self,
        fast_agent: Any,
        autonomy: Any,
        deep_search: Any = None,
        state_path: str | os.PathLike = "data/autonomy/overnight_plan.json",
        run_hour: int | None = None,
        run_minute: int | None = None,
        research_topics: list[str] | None = None,
    ):
        self.fast_agent = fast_agent
        self.autonomy = autonomy
        self.deep_search = deep_search
        self.state_path = Path(state_path)
        self.run_hour = int(os.getenv("JARVIS_OVERNIGHT_HOUR", "3")) if run_hour is None else int(run_hour)
        self.run_minute = int(os.getenv("JARVIS_OVERNIGHT_MINUTE", "0")) if run_minute is None else int(run_minute)
        if not 0 <= self.run_hour <= 23 or not 0 <= self.run_minute <= 59:
            raise ValueError("Overnight planning time must be a valid local HH:MM.")
        self.research_topics = (
            _configured_topics() if research_topics is None
            else _configured_topics(",".join(research_topics))
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _research(self) -> list[dict[str, str]]:
        """Research only explicit owner topics; each query has strict bounds."""
        if not self.deep_search:
            return []
        results = []
        for topic in self.research_topics:
            try:
                answer = self.deep_search.search(topic, limit=5)
                summary = " ".join(str(answer or "").split())[:MAX_RESEARCH_CHARS]
                results.append({
                    "topic": topic,
                    "status": "COMPLETED" if summary else "NO_EVIDENCE",
                    "summary": summary,
                })
            except Exception as exc:
                results.append({
                    "topic": topic,
                    "status": "FAILED",
                    "summary": f"Research unavailable ({type(exc).__name__}).",
                })
        return results

    def run_once(self) -> dict[str, Any]:
        """Generate bounded review suggestions and research configured topics."""
        status = self.autonomy.status()
        safe_status = {
            "pending_events": int(status.get("pending_events", 0)),
            "paused_events": int(status.get("paused_events", 0)),
            "pending_missions": int(status.get("pending_missions", 0)),
            "waiting_approval": int(status.get("waiting_approval", 0)),
            "failed_missions": int(status.get("failed_missions", 0)),
            "blocked_missions": int(status.get("blocked_missions", 0)),
            "completed_missions": int(status.get("completed_missions", 0)),
        }
        prompt = (
            "You are JARVIS performing a bounded overnight planning review. "
            "Use only these aggregate counters; do not infer private facts. "
            "Suggest at most three useful, low-risk diagnostic or organizational "
            "follow-ups for the owner to review tomorrow. Do not suggest sending "
            "messages, spending money, deleting/modifying files, changing settings, "
            "or interacting with people. Return JSON only: "
            '{"suggestions":["..."]}. Each suggestion must be one sentence, '
            "under 180 characters. If nothing needs attention, return an empty list.\n\n"
            + json.dumps(safe_status, sort_keys=True)
        )
        raw = self.fast_agent.ask(prompt)
        try:
            parsed = json.loads(str(raw or "{}"))
            suggestions = parsed.get("suggestions", [])
            if not isinstance(suggestions, list):
                raise ValueError("suggestions must be a list")
            cleaned = []
            for item in suggestions[:MAX_SUGGESTIONS]:
                value = " ".join(str(item).split())[:180]
                if value:
                    cleaned.append(value)
        except (ValueError, TypeError, json.JSONDecodeError):
            cleaned = []

        research = self._research()
        record = {
            "created_at": time.time(),
            "status": "READY_FOR_OWNER_REVIEW",
            "source_counters": safe_status,
            "suggestions": cleaned,
            "research_topics": list(self.research_topics),
            "research": research,
            "execution_performed": False,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        with self._lock:
            fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.state_path)
        return record

    def _seconds_until_next_run(self) -> float:
        now = datetime.now().astimezone()
        target = now.replace(
            hour=self.run_hour, minute=self.run_minute, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        return max(1.0, (target - now).total_seconds())

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="jarvis-overnight-planner", daemon=True
        )
        self._thread.start()
        return True

    def _run(self) -> None:
        while not self._stop.wait(self._seconds_until_next_run()):
            try:
                record = self.run_once()
                self.autonomy.ingest(
                    "overnight_planning",
                    {
                        "kind": "plan_ready",
                        "suggestion_count": len(record["suggestions"]),
                        "research_count": len(record["research"]),
                        "execution_performed": False,
                    },
                    event_id="overnight-" + datetime.now().astimezone().date().isoformat(),
                )
            except Exception:
                # A provider or storage failure must not kill JARVIS services.
                continue

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(max(0.0, min(float(timeout), 5.0)))
