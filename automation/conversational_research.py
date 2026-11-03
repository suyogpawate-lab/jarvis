"""Bounded conversational research with local Knowledge Hub evidence and change tracking."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from typing import Any

MAX_QUERY = 500
MAX_SUMMARY = 5000
MAX_RESULTS = 8
MAX_LOCAL_RESULTS = 8
MAX_LOCAL_SNIPPET = 700


def _clean(value: Any, limit: int = MAX_QUERY) -> str:
    return " ".join(str(value or "").split())[:limit]


class ConversationalResearch:
    def __init__(self, search_hub, deep_search, state_path="data/research/missions.json",
                 knowledge_hub_url="http://127.0.0.1:8766/api/search"):
        self.search_hub = search_hub
        self.deep_search = deep_search
        # Deliberately loopback-only: research must not turn this into an SSRF proxy.
        self.knowledge_hub_url = "http://127.0.0.1:8766/api/search"
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
        elif re.search(r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", lower):
            timing = "at"
        query = re.sub(r"\b(research|investigate|look into|study|monitor|track|keep track of)\b", "", raw, flags=re.I)
        query = re.sub(r"\b(tonight|this evening|later tonight|tomorrow|next day|every day|daily|every week|weekly|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", "", query, flags=re.I)
        query = re.sub(r"\b(and )?(brief me|report back|notify me|alert me|tell me|keep me updated)\b", "", query, flags=re.I)
        query = re.sub(r"\bwhen something significant happens\b", "", query, flags=re.I)
        query = _clean(query).strip(" ,.:;")
        if len(query) < 4:
            return None
        time_match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", lower, re.I)
        return {"query": query[:MAX_QUERY], "timing": timing,
                "schedule_at": time_match.group(0) if time_match else None}

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

    def cancel_mission(self, mission_or_job_id, scheduler):
        target = _clean(mission_or_job_id, 100)
        if not target:
            return "[ERROR] Supply a research mission or automation ID."
        with self._lock:
            records = self._load()
            matches = [r for r in records if r.get("id") == target or r.get("automation_id") == target]
            if not matches:
                return f"[ERROR] Research mission not found: {target}"
            record = matches[-1]
            if record.get("automation_id"):
                result = scheduler.cancel(record["automation_id"])
                if result.get("error"):
                    return "[ERROR] " + result["error"]
            record["status"] = "CANCELLED"
            record["cancelled_at"] = time.time()
            self._save(records)
        return f"Research mission {target} cancelled."

    def _knowledge_hub_search(self, query):
        payload = json.dumps({"query": query[:MAX_QUERY]}).encode("utf-8")
        request = Request(self.knowledge_hub_url, data=payload,
                          headers={"Content-Type": "application/json"},
                          method="POST")
        with urlopen(request, timeout=3) as response:
            data = json.loads(response.read(256_000).decode("utf-8", errors="replace"))
        rows = data.get("results", []) if isinstance(data, dict) else []
        return [{
            "provider": "knowledge_hub",
            "title": _clean(row.get("name", "Local document"), 200),
            "snippet": _clean(row.get("content", ""), MAX_LOCAL_SNIPPET),
            "chunk_no": row.get("chunk_no"),
        } for row in rows[:MAX_LOCAL_RESULTS] if isinstance(row, dict)]

    @staticmethod
    def _source_key(source):
        url = str(source.get("url") or "").strip().lower().rstrip("/")
        if url:
            return url
        return hashlib.sha256((source.get("provider", "") + "|" + source.get("title", "")).encode()).hexdigest()

    def research_now(self, query: str) -> str:
        query = _clean(query)
        if not query:
            return "[ERROR] Research topic is empty."
        started = time.time()
        providers, failures, sources = [], [], []
        local_evidence = []
        # Query provider registry once for auditable availability and source counts.
        try:
            for provider in list(getattr(self.search_hub, "providers", []) or []):
                name = str(getattr(provider, "name", type(provider).__name__))[:80]
                try:
                    found = provider.search(query, limit=MAX_RESULTS)
                    providers.append({"name": name, "status": "queried", "results": len(found or [])})
                except Exception as exc:
                    failures.append({"name": name, "error": type(exc).__name__})
        except Exception as exc:
            failures.append({"name": "search_hub", "error": type(exc).__name__})

        try:
            results = self.search_hub.search(query, limit=MAX_RESULTS)
            sources = [{"provider": str(getattr(item, "source", "unknown"))[:80],
                        "title": _clean(getattr(item, "title", ""), 240),
                        "url": str(getattr(item, "url", ""))[:1000]}
                       for item in (results or [])[:MAX_RESULTS]]
        except Exception as exc:
            failures.append({"name": "search_results", "error": type(exc).__name__})

        try:
            local_evidence = self._knowledge_hub_search(query)
            providers.append({"name": "knowledge_hub", "status": "queried",
                              "results": len(local_evidence)})
        except Exception as exc:
            failures.append({"name": "knowledge_hub", "error": type(exc).__name__})

        try:
            summary = str(self.deep_search.search(query, limit=MAX_RESULTS) or "").strip()
        except Exception as exc:
            summary = ""
            failures.append({"name": "deep_search", "error": type(exc).__name__})
        summary = summary[:MAX_SUMMARY]

        with self._lock:
            previous = [r for r in self._load()
                        if r.get("query", "").casefold() == query.casefold()
                        and r.get("status") in {"COMPLETED", "NO_EVIDENCE"}]
        prior_keys = {self._source_key(s) for r in previous for s in r.get("sources", [])}
        new_sources = [s for s in sources if self._source_key(s) not in prior_keys]
        local_lines = [f"- {x['title']}: {x['snippet']}" for x in local_evidence if x.get("snippet")]
        record = {
            "id": "research-" + uuid.uuid4().hex[:10], "query": query,
            "status": "COMPLETED" if summary else "NO_EVIDENCE",
            "created_at": started, "completed_at": time.time(), "summary": summary,
            "providers": providers, "provider_failures": failures, "sources": sources,
            "new_source_count": len(new_sources),
            "new_sources": new_sources,
            "local_evidence": local_evidence,
            "duration_seconds": round(time.time() - started, 2),
            "coverage_note": "Configured reachable providers, DeepSearch crawl and loopback Knowledge Hub only; not exhaustive internet coverage.",
        }
        self._record(record)
        if not summary:
            return "I couldn't produce a supported research summary. Check provider connectivity and the saved mission report."
        # On repeated runs, only source discovery is treated as a change signal.
        # A changed model summary alone is not called significant.
        if previous and not new_sources:
            return ("Monitoring check complete: no new source URLs were discovered since the previous run. "
                    "No significant-change notification is being raised.")
        source_lines = [f"- {s['provider']}: {s['title']} — {s['url']}" for s in (new_sources if previous else sources) if s.get("url")]
        local_block = ("\nLocal Knowledge Hub matches (not independently web-verified):\n" + "\n".join(local_lines[:6]) + "\n") if local_lines else ""
        failed_names = ", ".join(x["name"] for x in failures) or "none"
        return (f"Research complete.\n\n{summary}\n{local_block}\n"
                f"Providers queried: {', '.join(x['name'] for x in providers) or 'none'}. "
                f"Provider failures: {failed_names}.\n"
                + ("New sources:\n" + "\n".join(source_lines) + "\n" if source_lines else "")
                + "Coverage: configured reachable sources only; not the entire internet.")

    def schedule(self, query: str, timing: str, scheduler, timezone, schedule_at=None):
        now = datetime.now(timezone)
        if timing == "tomorrow":
            run_at = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        elif timing in {"tonight", "daily"}:
            run_at = now.replace(hour=21, minute=0, second=0, microsecond=0)
            if run_at <= now:
                run_at += timedelta(days=1)
        elif timing == "weekly":
            run_at = now + timedelta(days=7)
        else:
            match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", schedule_at or "", re.I)
            if not match:
                raise ValueError("Specify a time such as 'at 7:30 pm'.")
            hour, minute = int(match.group(1)), int(match.group(2) or 0)
            suffix = (match.group(3) or "").lower()
            if suffix == "pm" and hour < 12: hour += 12
            if suffix == "am" and hour == 12: hour = 0
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError("Invalid requested time.")
            run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if run_at <= now: run_at += timedelta(days=1)
        job = scheduler.schedule(
            command="research " + query, run_at=run_at.timestamp(),
            repeat_mode="daily" if timing == "daily" else None,
            repeat_at="21:00" if timing == "daily" else None,
            # Weekly cadence is calendar-based to avoid DST drift in follow-up.
            repeat_seconds=7 * 86400 if timing == "weekly" else None,
            description="Research: " + query[:180],
        )
        self._record({"id": "research-" + uuid.uuid4().hex[:10], "query": query,
                      "status": "SCHEDULED", "automation_id": job["id"],
                      "scheduled_for": job["next_run"], "recurrence": timing,
                      "created_at": time.time()})
        return f"Research scheduled as {job['id']} for {datetime.fromtimestamp(job['next_run'], timezone).strftime('%A %Y-%m-%d %H:%M %Z')}."
