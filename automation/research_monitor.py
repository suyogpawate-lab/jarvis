"""Bounded source-change detection and durable notification outbox."""
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

class ResearchMonitor:
    def __init__(self, directory="data/research", fetcher=None, notifier=None):
        self.directory = Path(directory)
        self.snapshot_path = self.directory / "source_snapshots.json"
        self.outbox_path = self.directory / "notification_outbox.json"
        self.fetcher = fetcher
        self.notifier = notifier

    def _read(self, path):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def _write(self, path, rows, limit=500):
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(rows[-limit:], stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def compare(self, sources):
        """Use an injected bounded fetcher; never fetch arbitrary URLs implicitly."""
        if self.fetcher is None:
            return [], [{"url": x.get("url", ""), "error": "source_fetcher_not_configured"}
                        for x in sources[:8]]
        previous = {x.get("url"): x for x in self._read(self.snapshot_path) if x.get("url")}
        changed, failures, updates = [], [], []
        for source in sources[:8]:
            url = str(source.get("url") or "")
            if not url.startswith("https://"):
                continue
            try:
                body = re.sub(r"\s+", " ", str(self.fetcher(url))).strip()[:192000]
                digest = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
                old = previous.get(url)
                if old and old.get("sha256") != digest:
                    changed.append({"url": url, "title": source.get("title", ""),
                                    "previous_hash": old.get("sha256"), "sha256": digest})
                updates.append({"url": url, "title": source.get("title", ""),
                                "sha256": digest, "checked_at": time.time()})
            except Exception as exc:
                failures.append({"url": url, "error": type(exc).__name__})
        if updates:
            merged = dict(previous)
            merged.update({x["url"]: x for x in updates})
            self._write(self.snapshot_path, list(merged.values()))
        return changed, failures

    @staticmethod
    def assess(summary, changed, new_sources):
        terms = ("breakthrough", "first-ever", "first successful", "major discovery",
                 "record efficiency", "production begins", "regulatory approval",
                 "announced", "demonstrated", "acquisition")
        text = str(summary or "").lower()
        signals = [term for term in terms if term in text]
        score = min(100, len(signals) * 18 + min(len(changed), 3) * 12
                    + min(len(new_sources), 3) * 5)
        return {"score": score, "level": "important" if score >= 35 else "informational",
                "signals": signals[:8],
                "method": "transparent_keyword_and_source_change_heuristic"}

    def _deliver(self, item, rows):
        """Deliver one durable outbox item with bounded exponential retry."""
        if self.notifier is None:
            return {"sent": False, "error": "notification_adapter_not_configured"}
        now = time.time()
        attempts = int(item.get("attempts", 0))
        if attempts >= 3 or float(item.get("retry_at", 0)) > now:
            return {"sent": False, "deferred": True}
        item["status"] = "PENDING"
        item["attempts"] = attempts + 1
        item["last_attempt_at"] = now
        self._write(self.outbox_path, rows)
        try:
            result = self.notifier(
                "JARVIS: " + str(item.get("level", "important")),
                str(item.get("summary", ""))[:900],
                item["id"],
            )
        except Exception as exc:
            result = {"ok": False, "error": type(exc).__name__}
        item["result"] = result
        if isinstance(result, dict) and result.get("ok"):
            item["status"] = "SENT"
            item["completed_at"] = time.time()
            item.pop("retry_at", None)
        else:
            item["status"] = "FAILED" if item["attempts"] >= 3 else "PENDING"
            item["retry_at"] = time.time() + min(3600, 60 * (2 ** (item["attempts"] - 1)))
        self._write(self.outbox_path, rows)
        return {"sent": item["status"] == "SENT", "result": result,
                "attempts": item["attempts"], "status": item["status"]}

    def retry_pending(self):
        """Retry due outbox entries; retries are bounded and use stable IDs."""
        rows = self._read(self.outbox_path)
        results = []
        for item in rows:
            if item.get("status") == "PENDING" and int(item.get("attempts", 0)) < 3:
                if float(item.get("retry_at", 0)) <= time.time():
                    results.append(self._deliver(item, rows))
        return results

    def notify_once(self, query, evidence, summary, assessment):
        fingerprint = hashlib.sha256((query.casefold() + "|" +
            "|".join(sorted(x.get("url", "") + ":" + x.get("sha256", x.get("content_hash", "")) for x in evidence))).encode()).hexdigest()
        rows = self._read(self.outbox_path)
        existing = next((x for x in reversed(rows)
                         if x.get("fingerprint") == fingerprint), None)
        if existing and existing.get("status") == "SENT":
            return {"sent": False, "duplicate": True}
        if existing:
            return self._deliver(existing, rows)
        item = {"id": "research-" + uuid.uuid4().hex[:10], "fingerprint": fingerprint,
                "query": query, "summary": str(summary)[:900],
                "level": assessment.get("level", "important"),
                "status": "PENDING", "attempts": 0, "retry_at": 0,
                "created_at": time.time()}
        rows.append(item)
        self._write(self.outbox_path, rows)
        return self._deliver(item, rows)

    def status(self):
        rows = self._read(self.outbox_path)
        return {"tracked_sources": len(self._read(self.snapshot_path)),
                "pending_notifications": sum(x.get("status") == "PENDING" for x in rows),
                "failed_notifications": sum(x.get("status") == "FAILED" for x in rows)}
