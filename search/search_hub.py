"""
JARVIS Search Hub.

Provides one normalized interface over multiple search providers.
Providers are optional: unavailable providers are skipped gracefully.
"""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import json

from .tor_transport import TorTransport
from .cache import SearchCache, ttl_for_query


@dataclass
class SearchResult:
    source: str
    title: str
    url: str
    snippet: str = ""
    content: str = ""
    published_at: Optional[str] = None
    relevance: float = 0.0


class SearchHub:
    def __init__(self, tor_transport=None):
        self.providers = []
        self.tor = tor_transport or TorTransport()
        self.cache = SearchCache()

    def register(self, provider):
        self.providers.append(provider)

    def fetch(self, url, use_tor=False, timeout=15):
        """
        Fetch a URL through the selected transport.

        Normal fetches use urllib directly.
        Tor fetches use the existing JARVIS TorTransport.
        """
        if use_tor:
            return self.tor.fetch(url)

        request = Request(
            url,
            headers={"User-Agent": "JARVIS-SearchHub/1.0"},
        )

        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def search(self, query, limit=10):
        cache_ttl = ttl_for_query(query)
        cached = self.cache.get(
            "web-search",
            query,
            variant=str(limit),
            ttl_seconds=cache_ttl,
        )
        if isinstance(cached, list):
            try:
                print(f" [WEB CACHE] Reusing saved search results for: {query[:80]}")
                return [SearchResult(**item) for item in cached if isinstance(item, dict)]
            except (TypeError, ValueError):
                pass

        results = []
        for provider in self.providers:
            try:
                results.extend(provider.search(query, limit=limit))
            except Exception:
                continue

        results = self._deduplicate(results)
        results.sort(
            key=lambda r: (
                -float(r.relevance or 0.0),
                r.source,
                r.title.lower(),
            )
        )

        selected = []
        providers_seen = set()
        for result in results:
            if result.source not in providers_seen:
                selected.append(result)
                providers_seen.add(result.source)
            if len(selected) >= limit:
                break

        if len(selected) < limit:
            for result in results:
                if result in selected:
                    continue
                selected.append(result)
                if len(selected) >= limit:
                    break

        selected = selected[:limit]
        if selected:
            self.cache.put(
                "web-search",
                query,
                [vars(item) for item in selected],
                variant=str(limit),
                ttl_seconds=cache_ttl,
            )
            print(f" [WEB CACHE] Saved {len(selected)} search results locally.")
        return selected

    @staticmethod
    def _deduplicate(results):
        seen = set()
        unique = []

        for result in results:
            raw_url = (result.url or "").strip()

            if not raw_url:
                continue

            parts = urlsplit(raw_url)
            normalized_url = urlunsplit(
                (
                    parts.scheme.lower(),
                    parts.netloc.lower(),
                    unquote(parts.path).rstrip("/"),
                    parts.query,
                    "",
                )
            )

            key = normalized_url.lower()

            if key in seen:
                continue

            seen.add(key)
            result.url = normalized_url
            unique.append(result)

        return unique


class DuckDuckGoProvider:
    name = "duckduckgo"

    def search(self, query, limit=10):
        url = (
            "https://api.duckduckgo.com/"
            f"?q={quote(query)}"
            "&format=json"
            "&no_html=1"
            "&skip_disambig=1"
        )

        request = Request(
            url,
            headers={"User-Agent": "JARVIS-SearchHub/1.0"},
        )

        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))

        results = []

        abstract_url = data.get("AbstractURL")
        abstract = data.get("AbstractText")

        if abstract_url and abstract:
            results.append(
                SearchResult(
                    source=self.name,
                    title=data.get("Heading") or query,
                    url=abstract_url,
                    snippet=abstract,
                    content=abstract,
                    relevance=1.0,
                )
            )

        for topic in data.get("RelatedTopics", []):
            if not isinstance(topic, dict):
                continue

            url = topic.get("FirstURL")
            text = topic.get("Text")

            if not url or not text:
                continue

            results.append(
                SearchResult(
                    source=self.name,
                    title=text.split(" - ")[0][:200],
                    url=url,
                    snippet=text,
                    relevance=0.5,
                )
            )

            if len(results) >= limit:
                break

        return results


class WikipediaProvider:
    name = "wikipedia"

    def search(self, query, limit=10):
        url = (
            "https://en.wikipedia.org/w/api.php"
            f"?action=query&list=search&srsearch={quote(query)}"
            "&format=json&utf8=1"
            f"&srlimit={min(limit, 20)}"
        )

        request = Request(
            url,
            headers={"User-Agent": "JARVIS-SearchHub/1.0"},
        )

        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))

        results = []

        for index, item in enumerate(
            data.get("query", {}).get("search", [])
        ):
            title = item.get("title", "")
            snippet = item.get("snippet", "")

            results.append(
                SearchResult(
                    source=self.name,
                    title=title,
                    url=(
                        "https://en.wikipedia.org/wiki/"
                        + quote(title.replace(" ", "_"))
                    ),
                    snippet=snippet,
                    relevance=1.0 / (index + 1),
                )
            )

        return results


from .providers.web_engines import BraveSearchProvider, BingSearchProvider
from .providers.community import GitHubProvider, RedditProvider


def build_default_search_hub():
    hub = SearchHub()
    hub.register(DuckDuckGoProvider())
    hub.register(WikipediaProvider())
    hub.register(BraveSearchProvider())
    hub.register(BingSearchProvider())
    hub.register(GitHubProvider())
    hub.register(RedditProvider())
    return hub
