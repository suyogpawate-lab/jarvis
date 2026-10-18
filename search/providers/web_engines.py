import json
import os
from urllib.parse import quote
from urllib.request import Request, urlopen

from search.search_hub import SearchResult


class BraveSearchProvider:
    name = "brave"

    def __init__(self):
        self.api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()

    def search(self, query, limit=10):
        if not self.api_key:
            return []

        url = (
            "https://api.search.brave.com/res/v1/web/search"
            f"?q={quote(query)}&count={min(limit, 20)}"
        )

        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
                "User-Agent": "JARVIS-SearchHub/1.0",
            },
        )

        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))

        results = []

        for index, item in enumerate(
            data.get("web", {}).get("results", [])
        ):
            results.append(
                SearchResult(
                    source=self.name,
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    relevance=1.0 / (index + 1),
                )
            )

        return results


class BingSearchProvider:
    name = "bing"

    def __init__(self):
        self.api_key = os.environ.get("BING_SEARCH_API_KEY", "").strip()

    def search(self, query, limit=10):
        if not self.api_key:
            return []

        url = (
            "https://api.bing.microsoft.com/v7.0/search"
            f"?q={quote(query)}&count={min(limit, 50)}"
        )

        request = Request(
            url,
            headers={
                "Ocp-Apim-Subscription-Key": self.api_key,
                "User-Agent": "JARVIS-SearchHub/1.0",
            },
        )

        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))

        results = []

        for index, item in enumerate(
            data.get("webPages", {}).get("value", [])
        ):
            results.append(
                SearchResult(
                    source=self.name,
                    title=item.get("name", ""),
                    url=item.get("url", ""),
                    snippet=item.get("snippet", ""),
                    relevance=1.0 / (index + 1),
                )
            )

        return results
