import json
from urllib.parse import quote
from urllib.request import Request, urlopen

from search.search_hub import SearchResult


class GitHubProvider:
    name = "github"

    def search(self, query, limit=10):
        url = (
            "https://api.github.com/search/repositories"
            f"?q={quote(query)}&per_page={min(limit, 30)}"
        )

        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "JARVIS-SearchHub/1.0",
            },
        )

        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))

        results = []

        for index, item in enumerate(data.get("items", [])):
            description = item.get("description") or ""

            results.append(
                SearchResult(
                    source=self.name,
                    title=item.get("full_name", ""),
                    url=item.get("html_url", ""),
                    snippet=description,
                    relevance=1.0 / (index + 1),
                )
            )

        return results


class RedditProvider:
    name = "reddit"

    def search(self, query, limit=10):
        url = (
            "https://www.reddit.com/search.json"
            f"?q={quote(query)}&limit={min(limit, 25)}"
        )

        request = Request(
            url,
            headers={
                "User-Agent": "JARVIS-SearchHub/1.0",
            },
        )

        try:
            with urlopen(request, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            # Reddit may reject unauthenticated requests.
            # Search Hub should simply treat it as unavailable.
            return []

        results = []

        children = (
            data.get("data", {})
            .get("children", [])
        )

        for index, child in enumerate(children):
            item = child.get("data", {})

            permalink = item.get("permalink", "")
            if permalink.startswith("/"):
                permalink = "https://www.reddit.com" + permalink

            results.append(
                SearchResult(
                    source=self.name,
                    title=item.get("title", ""),
                    url=permalink,
                    snippet=item.get("selftext", "")[:500],
                    published_at=str(item.get("created_utc", "")),
                    relevance=1.0 / (index + 1),
                )
            )

        return results
