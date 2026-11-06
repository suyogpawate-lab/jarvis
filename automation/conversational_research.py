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
from automation.research_monitor import ResearchMonitor
from automation.overnight_research import OvernightResearch

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
        self.state_path = Path(state_path)
        self.overnight = OvernightResearch(
            search_hub, getattr(deep_search, "fast_agent", None),
            state_path=str(self.state_path.parent / "overnight.json"),
        )
        # Deliberately loopback-only: research must not turn this into an SSRF proxy.
        self.knowledge_hub_url = "http://127.0.0.1:8766/api/search"
        self._lock = threading.RLock()
        self.whatsapp_sender = None
        self.monitor = ResearchMonitor(
            directory=str(self.state_path.parent),
            fetcher=self._fetch_monitor_source,
            notifier=self._send_monitor_notification,
        )

    def _fetch_monitor_source(self, url):
        """Fetch public HTTPS source text with DNS/IP and redirect guards."""
        import ipaddress
        import socket
        from html.parser import HTMLParser
        from urllib.parse import urlsplit
        from urllib.request import Request, build_opener, HTTPRedirectHandler

        parts = urlsplit(str(url))
        if (parts.scheme != "https" or not parts.hostname or parts.username
                or parts.password or parts.port not in (None, 443)):
            raise ValueError("source URL must be public HTTPS on port 443")
        host = parts.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith((".local", ".internal")):
            raise ValueError("local source host rejected")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(
                host, 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ValueError("source DNS resolution failed") from exc
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError("source resolves to a non-public IP")

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise ValueError("source redirects are not followed")

        request = Request(str(url), headers={"User-Agent": "JARVIS-ResearchMonitor/1.0"})
        opener = build_opener(NoRedirect)
        with opener.open(request, timeout=5) as response:
            final = urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != host:
                raise ValueError("source origin changed")
            raw = response.read(512_001)
        if len(raw) > 512_000:
            raw = raw[:512_000]
        html = raw.decode("utf-8", errors="replace")

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
                self.hidden = 0
            def handle_starttag(self, tag, attrs):
                if tag.lower() in {"script", "style", "noscript", "svg"}:
                    self.hidden += 1
            def handle_endtag(self, tag):
                if tag.lower() in {"script", "style", "noscript", "svg"} and self.hidden:
                    self.hidden -= 1
            def handle_data(self, data):
                if not self.hidden:
                    self.parts.append(data)

        parser = TextExtractor()
        parser.feed(html)
        return " ".join(" ".join(parser.parts).split())[:192000]

    def set_whatsapp_sender(self, sender):
        """Attach an explicitly configured owner-DM delivery adapter."""
        self.whatsapp_sender = sender

    def _send_monitor_notification(self, title, content, alert_id):
        import shutil
        import subprocess
        outcomes = {}
        executable = shutil.which("termux-notification")
        if executable:
            try:
                result = subprocess.run(
                    [executable, "--id", alert_id[:32], "--title", title[:100],
                     "--content", content[:900], "--priority", "high"],
                    capture_output=True, text=True, timeout=8, check=False,
                )
                outcomes["termux"] = {"ok": result.returncode == 0, "exit": result.returncode,
                                      "error": (result.stderr or "")[:250]}
            except Exception as exc:
                outcomes["termux"] = {"ok": False, "error": type(exc).__name__}
        else:
            outcomes["termux"] = {"ok": False, "error": "termux-notification unavailable"}

        recipient = re.sub(r"\\D", "", os.getenv("JARVIS_WA_RESEARCH_NOTIFY_TO", ""))
        if recipient and self.whatsapp_sender:
            if not 10 <= len(recipient) <= 15:
                outcomes["whatsapp"] = {"ok": False, "error": "configured owner number must contain 10-15 digits"}
            else:
                try:
                    result = self.whatsapp_sender(recipient, f"{title}\\n{content}"[:1200])
                    outcomes["whatsapp"] = {"ok": bool(result), "result": str(result)[:200]}
                except Exception as exc:
                    outcomes["whatsapp"] = {"ok": False, "error": type(exc).__name__}
        elif recipient:
            outcomes["whatsapp"] = {"ok": False, "error": "WhatsApp worker unavailable"}
        else:
            outcomes["whatsapp"] = {"ok": False, "error": "not configured"}

        return {"ok": any(item.get("ok") for item in outcomes.values()), "channels": outcomes}

    @staticmethod
    def parse_request(text: str) -> dict[str, Any] | None:
        raw = _clean(text)
        lower = raw.lower()
        # Only treat an explicit research/monitoring verb at the start as
        # research intent. Merely mentioning "research" in a scheduler,
        # status, or administrative request must never launch a research run.
        research_intent = re.match(
            r"^(?:please\s+)?(?:overnight\s+)?(?:jarvis[, ]+)?(?:can you\s+|could you\s+|would you\s+)?"
            r"(?:research|investigate|look into|study)\b",
            raw, re.I,
        ) or re.match(
            r"^(?:please\s+)?(?:research|investigate|look into|study)\s+overnight\b",
            raw, re.I,
        )
        monitoring_intent = re.match(
            r"^(?:please\s+)?(?:jarvis[, ]+)?(?:keep track of|monitor|track)\b",
            raw, re.I,
        )
        if not (research_intent or monitoring_intent):
            return None
        recurring = re.search(r"\b(every day|daily|every week|weekly)\b", lower)
        if not recurring and re.search(r"\b(keep track of|monitor|track)\b", lower) and re.search(r"\b(notify me|alert me|keep me updated)\b", lower):
            recurring = re.search(r"\b(daily)\b", "daily")
        timing = "now"
        if re.search(r"\bovernight\b", lower):
            timing = "overnight"
        elif recurring:
            timing = "daily" if recurring.group(1) in {"every day", "daily"} else "weekly"
        elif re.search(r"\b(tomorrow|next day)\b", lower):
            timing = "tomorrow"
        elif re.search(r"\b(tonight|this evening|later tonight)\b", lower):
            timing = "tonight"
        elif re.search(r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", lower):
            timing = "at"
        query = re.sub(r"\b(research|investigate|look into|keep track of|study|monitor|track)\b", "", raw, flags=re.I)
        query = re.sub(r"\b(overnight|tonight|this evening|later tonight|tomorrow|next day|every day|daily|every week|weekly|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", "", query, flags=re.I)
        query = re.sub(r"\b(and )?(brief me|report back|notify me|alert me|tell me|keep me updated)\b", "", query, flags=re.I)
        query = re.sub(r"\bwhen something significant happens\b", "", query, flags=re.I)
        query = re.sub(r"^\s*overnight\s+on\s+", "", query, flags=re.I)
        query = re.sub(r"\b(?:and\s+)?show\s+me\s+(?:the\s+)?results?\b", "", query, flags=re.I)
        query = re.sub(r"^\s*on\s+", "", query, flags=re.I)
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

    def status(self, scheduler=None):
        with self._lock:
            missions = self._load()
        counts = {}
        for item in missions:
            state = str(item.get("status", "UNKNOWN"))
            if scheduler is not None and item.get("automation_id"):
                job = scheduler.get(item["automation_id"]) or {}
                state = str(job.get("status", state))
                item["status"] = state
                if job.get("last_result") is not None:
                    item["last_result"] = str(job["last_result"])[:500]
                if job.get("last_run") is not None:
                    item["last_run"] = job["last_run"]
            counts[state] = counts.get(state, 0) + 1
        overnight = self.overnight.status()
        for item in overnight.get("missions", []):
            state = str(item.get("status", "UNKNOWN"))
            counts[state] = counts.get(state, 0) + 1
        return {"mission_counts": counts, "recent_missions": missions[-10:],
                "overnight": overnight, "monitor": self.monitor.status()}

    def start_overnight(self, query: str) -> str:
        return self.overnight.start(query)

    def cancel_overnight(self, mission_id: str) -> str:
        return self.overnight.cancel(mission_id)

    def resume_overnight(self, mission_id: str) -> str:
        return self.overnight.resume(mission_id)

    def resume_mission(self, mission_or_job_id, scheduler):
        target = _clean(mission_or_job_id, 100)
        if not target:
            return "[ERROR] Supply a research mission or automation ID."
        with self._lock:
            records = self._load()
            matches = [r for r in records if r.get("id") == target or r.get("automation_id") == target]
            if not matches:
                return f"[ERROR] Research mission not found: {target}"
            record = matches[-1]
            automation_id = record.get("automation_id") or target
            result = scheduler.resume_recovered(automation_id)
            if result.get("error"):
                return "[ERROR] " + result["error"]
            record["status"] = "SCHEDULED"
            record["resumed_at"] = time.time()
            self._save(records)
        return f"Research mission {target} explicitly resumed as {automation_id}; it is queued to run once."

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

    def research_now(self, query: str, notify: bool = False) -> str:
        query = _clean(query)
        if not query:
            return "[ERROR] Research topic is empty."
        started = time.time()
        if notify:
            self.monitor.retry_pending()
        providers, failures, sources = [], [], []
        local_evidence = []
        # Query provider registry once for auditable availability and source counts.
        try:
            for provider in list(getattr(self.search_hub, "providers", []) or []):
                name = str(getattr(provider, "name", type(provider).__name__))[:80]
                try:
                    found = provider.search(query, limit=MAX_RESULTS)
                    providers.append({"name": name, "status": "queried", "results": len(found or [])})
                    for item in (found or []):
                        url = str(getattr(item, "url", ""))[:1000]
                        if not url:
                            continue
                        sources.append({
                            "provider": name,
                            "title": _clean(getattr(item, "title", ""), 240),
                            "url": url,
                        })
                except Exception as exc:
                    failures.append({"name": name, "error": type(exc).__name__})
        except Exception as exc:
            failures.append({"name": "search_hub", "error": type(exc).__name__})

        # Use direct provider results rather than SearchHub.search(), whose
        # cache can hide new sources during recurring monitoring.
        sources = sources[:MAX_RESULTS]

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
        changed_sources, source_fetch_failures = self.monitor.compare(sources)
        significance = self.monitor.assess(summary, changed_sources, new_sources)
        local_lines = [f"- {x['title']}: {x['snippet']}" for x in local_evidence if x.get("snippet")]
        record = {
            "id": "research-" + uuid.uuid4().hex[:10], "query": query,
            "status": "COMPLETED" if summary else "NO_EVIDENCE",
            "created_at": started, "completed_at": time.time(), "summary": summary,
            "providers": providers, "provider_failures": failures, "sources": sources,
            "new_source_count": len(new_sources),
            "new_sources": new_sources,
            "changed_sources": changed_sources,
            "source_fetch_failures": source_fetch_failures,
            "significance": significance,
            "local_evidence": local_evidence,
            "duration_seconds": round(time.time() - started, 2),
            "coverage_note": "Configured reachable providers, DeepSearch crawl and loopback Knowledge Hub only; not exhaustive internet coverage.",
        }
        self._record(record)
        if not summary:
            return "I couldn't produce a supported research summary. Check provider connectivity and the saved mission report."
        delivery = None
        if notify and previous and (changed_sources or new_sources) and significance["level"] == "important":
            delivery = self.monitor.notify_once(query, changed_sources + new_sources, summary, significance)
        if previous and not new_sources and not changed_sources:
            return ("Monitoring check complete: no new source URLs or changed source content were detected. "
                    f"Source fetch failures: {len(source_fetch_failures)}.")
        source_lines = [f"- {s.get('provider', 'content-change')}: {s.get('title', 'Source') } — {s['url']}" for s in (changed_sources + new_sources if previous else sources) if s.get("url")]
        local_block = ("\nLocal Knowledge Hub matches (not independently web-verified):\n" + "\n".join(local_lines[:6]) + "\n") if local_lines else ""
        failed_names = ", ".join(x["name"] for x in failures) or "none"
        return (f"Research complete.\n\n{summary}\n{local_block}\n"
                f"Providers queried: {', '.join(x['name'] for x in providers) or 'none'}. "
                f"Provider failures: {failed_names}.\n"
                + ("New sources:\n" + "\n".join(source_lines) + "\n" if source_lines else "")
                + f"\nContent changes: {len(changed_sources)}; new URLs: {len(new_sources)}; significance: {significance['level']} ({significance['score']}/100)."
                + f"\nSource fetch failures: {len(source_fetch_failures)}."
                + ("\nNotification: sent." if delivery and delivery.get("sent") else "\nNotification: delivery failed or unavailable." if notify and delivery else "\nNotification: not requested.")
                + " Coverage: configured reachable sources only; not the entire internet.")

    def schedule(self, query: str, timing: str, scheduler, timezone, schedule_at=None):
        now = datetime.now(timezone)
        if timing == "tomorrow":
            hour, minute = 9, 0
            if schedule_at:
                match = re.search(
                    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
                    str(schedule_at), re.I,
                )
                if not match:
                    raise ValueError("Specify a valid time such as 'at 5:00 am'.")
                hour, minute = int(match.group(1)), int(match.group(2) or 0)
                suffix = (match.group(3) or "").lower()
                if suffix:
                    if not 1 <= hour <= 12:
                        raise ValueError("12-hour clock values must be between 1 and 12.")
                    if suffix == "pm" and hour != 12:
                        hour += 12
                    elif suffix == "am" and hour == 12:
                        hour = 0
                if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                    raise ValueError("Invalid requested time.")
            run_at = (now + timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
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
            repeat_mode=timing if timing in {"daily", "weekly"} else None,
            repeat_at="21:00" if timing == "daily" else None,
            description="Research: " + query[:180],
        )
        self._record({"id": "research-" + uuid.uuid4().hex[:10], "query": query,
                      "status": "SCHEDULED", "automation_id": job["id"],
                      "scheduled_for": job["next_run"], "recurrence": timing,
                      "created_at": time.time()})
        return f"Research scheduled as {job['id']} for {datetime.fromtimestamp(job['next_run'], timezone).strftime('%A %Y-%m-%d %H:%M %Z')}."
