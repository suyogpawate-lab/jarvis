"""Conversational research missions for JARVIS.

Natural-language intake is shared by voice and text through CommandDispatcher.
Research is bounded, source-aware, persistent, and read-only.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


MAX_QUERY = 500
MAX_SUMMARY = 5000
MAX_RESULTS = 8
MAX_SECONDS = 180


def _clean(value: Any, limit: int = MAX_QUERY) -> str:
    return " ".join(str(value or "").split())[:limit]


class ConversationalResearch:
    def __init__(self, search_hub, deep_search, state_path="data/research/missions.json"):
        self.search_hub = search_hub
        self.deep_search = deep_search
        self.state_path = Path(state_path)
        self._lock = threading.RLock()

    @staticmethod
    def parse_request(text: str) -> dict[str, Any] | None:
        raw = _clean(text)
        lower = raw.lower()
        if not re.search(r"\b(research|investigate|look into|study|monitor|track|keep track of)\b", lower):
            return None
        recurring = re.search(r"\b(every day|daily|every week|weekly)\b", lower)
        if not recurring and re.search(r"\b(keep track of|monitor|track)\b", lower) and re.search(r"\b(notify me|alert me|keep me updated)\b", lower):
            recurring = re.search(r"\b(daily)\b", "daily")
        timing = "now"
        if recurring:
            timing = "daily" if recurring.group(1) in {"every day", "daily"} else "weekly"
        elif re.search(r"\b(tomorrow|next day)\b", lower):
            timing = "tomorrow"
        elif re.search(r"\b(tonight|this evening|later tonight)\b", lower):
            timing = "tonight"
        elif re.search(r"\b(at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", lower):
            timing = "at"
        query = re.sub(r"\b(research|investigate|look into|study|monitor|track|keep track of)\b", "", raw, flags=re.I)
        query = re.sub(r"\b(tonight|this evening|later tonight|tomorrow|next day|every day|daily|every week|weekly|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", "", query, flags=re.I)
        query = re.sub(r"\b(and )?(brief me|report back|notify me|alert me|tell me|keep me updated)\b", "", query, flags=re.I)
        query = re.sub(r"\bwhen something significant happens\b", "", query, flags=re.I)
        query = _clean(query).strip(" ,.:;")
        if len(query) < 4:
            return None
        time_match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", lower, re.I)
        schedule_at = time_match.group(0) if time_match else None
        return {"query": query[:MAX_QUERY], "timing": timing, "schedule_at": schedule_at}

    def _load(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def _save(self, records):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".json.tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(records[-100:], stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.state_path)

    def _record(self, record):
        with self._lock:
            records = self._load()
            records.append(record)
            self._save(records)

    def list_missions(self):
        with self._lock:
            return self._load()[-20:]

    def research_now(self, query: str) -> str:
        query = _clean(query)
        if not query:
            return "[ERROR] Research topic is empty."
        mission_id = "research-" + uuid.uuid4().hex[:10]
        started = time.time()
        providers = []
        failures = []
        try:
            provider_list = list(getattr(self.search_hub, "providers", []) or [])
            for provider in provider_list:
                name = str(getattr(provider, "name", type(provider).__name__))[:80]
                try:
                    found = provider.search(query, limit=MAX_RESULTS)
                    providers.append({"name": name, "status": "queried", "results": len(found or [])})
                except Exception as exc:
                    failures.append({"name": name, "error": type(exc).__name__})
        except Exception as exc:
            failures.append({"name": "search_hub", "error": type(exc).__name__})
        try:
            summary = str(self.deep_search.search(query, limit=MAX_RESULTS) or "").strip()
        except Exception as exc:
            summary = ""
            failures.append({"name": "deep_search", "error": type(exc).__name__})
        summary = summary[:MAX_SUMMARY]
        sources = []
        try:
            results = self.search_hub.search(query, limit=MAX_RESULTS)
            sources = [
                {"provider": str(getattr(item, "source", "unknown"))[:80],
                 "title": _clean(getattr(item, "title", ""), 240),
                 "url": str(getattr(item, "url", ""))[:1000]}
                for item in (results or [])[:MAX_RESULTS]
            ]
        except Exception as exc:
            failures.append({"name": "search_results", "error": type(exc).__name__})
        record = {
            "id": mission_id, "query": query, "status": "COMPLETED" if summary else "NO_EVIDENCE",
            "created_at": started, "completed_at": time.time(),
            "summary": summary, "providers": providers, "provider_failures": failures,
            "sources": sources, "duration_seconds": round(time.time() - started, 2),
            "coverage_note": "Only configured providers and reachable pages were searched; this is not exhaustive internet coverage.",
        }
        self._record(record)
        if not summary:
            return "I couldn't produce a supported research summary. Check provider connectivity and the saved mission report."
        source_lines = [f"- {s['provider']}: {s['title']} — {s['url']}" for s in sources if s.get("url")]
        failed_names = ", ".join(x["name"] for x in failures) or "none"
        return (
            f"Research complete.\n\n{summary}\n\n"
            f"Providers queried: {', '.join(x['name'] for x in providers) or 'none'}. "
            f"Provider failures: {failed_names}.\n"
            + ("Sources:\n" + "\n".join(source_lines) + "\n" if source_lines else "")
            + "Coverage: configured/reachable sources only; not the entire internet."
        )

    def schedule(self, query: str, timing: str, scheduler, timezone, schedule_at=None):
        now = datetime.now(timezone)
        if timing == "tomorrow":
            run_at = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        elif timing == "tonight":
            run_at = now.replace(hour=21, minute=0, second=0, microsecond=0)
            if run_at <= now:
                run_at += timedelta(days=1)
        elif timing == "daily":
            run_at = now.replace(hour=21, minute=0, second=0, microsecond=0)
            if run_at <= now:
                run_at += timedelta(days=1)
        elif timing == "weekly":
            run_at = now + timedelta(days=7)
        else:
            match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", schedule_at or "", re.I)
            hour = int(match.group(1)) if match else 9
            minute = int(match.group(2) or 0) if match else 0
            suffix = (match.group(3) or "").lower() if match else ""
            if suffix == "pm" and hour < 12: hour += 12
            if suffix == "am" and hour == 12: hour = 0
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError("Invalid requested time.")
            run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if run_at <= now: run_at += timedelta(days=1)
        command = "research " + query
        job = scheduler.schedule(
            command=command, run_at=run_at.timestamp(),
            repeat_mode="daily" if timing == "daily" else None,
            repeat_at="21:00" if timing == "daily" else None,
            repeat_seconds=7 * 86400 if timing == "weekly" else None,
            description="Research: " + query[:180],
        )
        self._record({
            "id": "research-" + uuid.uuid4().hex[:10], "query": query,
            "status": "SCHEDULED", "automation_id": job["id"],
            "scheduled_for": job["next_run"], "recurrence": timing,
            "created_at": time.time(),
        })
        return f"Research scheduled as {job['id']} for {datetime.fromtimestamp(job['next_run'], timezone).strftime('%A %Y-%m-%d %H:%M %Z')}."
