"""Small persistent JSON cache for JARVIS web-search results.

Cache files live outside the repository by default so personal research history
is not committed to GitHub. Cache failures never block a search.
"""
import hashlib
import json
import os
import re
import tempfile
import time


def ttl_for_query(query, stable=7 * 86400, volatile=3600):
    """Shorten cache lifetime for questions likely to change quickly."""
    normalized = " ".join(str(query or "").lower().split())
    terms = re.findall(r"[a-z0-9]+", normalized)
    volatile_terms = {
        "today", "tonight", "now", "current", "currently", "latest",
        "recent", "news", "weather", "price", "prices", "stock", "stocks",
        "score", "scores", "live", "traffic", "forecast", "availability",
        "exchange", "rate", "version", "released", "release", "schedule",
        "election", "outage", "tomorrow", "yesterday",
    }
    return volatile if (volatile_terms.intersection(terms) or "this week" in normalized) else stable


class SearchCache:
    def __init__(self, path=None, max_entries=300):
        self.path = os.path.expanduser(
            path or os.getenv(
                "JARVIS_WEB_CACHE_PATH",
                "~/.cache/jarvis/web_search_cache.json",
            )
        )
        self.max_entries = max(20, int(max_entries))

    @staticmethod
    def _key(namespace, query, variant=""):
        normalized = " ".join(str(query or "").lower().split())
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
        raw = f"{namespace}\n{normalized}\n{variant}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def get(self, namespace, query, variant="", ttl_seconds=86400):
        key = self._key(namespace, query, variant)
        data = self._load()
        entry = data.get(key)
        if not isinstance(entry, dict):
            return None
        try:
            created = float(entry.get("created_at", 0))
            expires = float(entry.get("expires_at", 0))
        except (TypeError, ValueError):
            return None
        now = time.time()
        if expires <= now or now - created > max(1, int(ttl_seconds)):
            data.pop(key, None)
            self._write(data)
            return None
        return entry.get("value")

    def put(self, namespace, query, value, variant="", ttl_seconds=86400):
        key = self._key(namespace, query, variant)
        now = time.time()
        data = self._load()
        data[key] = {
            "namespace": str(namespace),
            "query": " ".join(str(query or "").split())[:500],
            "variant": str(variant),
            "created_at": now,
            "expires_at": now + max(1, int(ttl_seconds)),
            "value": value,
        }
        if len(data) > self.max_entries:
            ordered = sorted(
                data.items(),
                key=lambda item: float(item[1].get("created_at", 0))
                if isinstance(item[1], dict) else 0,
                reverse=True,
            )
            data = dict(ordered[:self.max_entries])
        self._write(data)

    def _write(self, data):
        try:
            directory = os.path.dirname(self.path)
            os.makedirs(directory, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=".web-cache-", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError:
            # The search must still work if storage is read-only or full.
            pass
