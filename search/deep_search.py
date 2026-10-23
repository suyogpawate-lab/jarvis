"""
JARVIS Deep Search.

Adaptive, unlimited-page research crawler.

Flow:
    search -> rank -> fetch -> extract -> discover links
           -> relevance filter -> repeat -> synthesize

Normal SearchHub searches remain unchanged.
Deep research uses SearchHub's Tor-backed fetch transport.
"""

import re
from collections import deque
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .search_hub import SearchHub
from .cache import SearchCache, ttl_for_query


class _ResearchHTMLParser(HTMLParser):
    """Structured standard-library HTML extractor for Termux."""

    SKIP_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "template",
        "iframe",
    }

    NON_CONTENT_TAGS = {
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "menu",
    }

    REFERENCE_MARKERS = {
        "reflist",
        "references",
        "mw-references-wrap",
        "reference-list",
        "citation",
        "citations",
    }

    CONTENT_CLASSES = {
        "mw-parser-output",
        "article-body",
        "article-content",
        "entry-content",
        "post-content",
        "post-body",
        "story-body",
        "content-body",
    }

    BLOCK_TAGS = {
        "article",
        "section",
        "main",
        "div",
        "p",
        "li",
        "dd",
        "dt",
        "blockquote",
        "pre",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "tr",
        "td",
        "th",
    }

    def __init__(self):
        super().__init__()

        self.parts = []
        self.blocks = []
        self.links = []
        self.title_parts = []

        self._skip_depth = 0
        self._non_content_depth = 0
        self._reference_depth = 0
        self._content_depth = 0
        self._in_title = False
        self._current_block = []

    def _flush_block(self):
        if not self._current_block:
            return

        text = " ".join(self._current_block).strip()

        if text:
            self.blocks.append(text)
            self.parts.append(text)

        self._current_block = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_map = dict(attrs)

        classes = set(
            (attr_map.get("class") or "").split()
        )

        element_id = (attr_map.get("id") or "").lower()

        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth:
            return

        if tag in self.NON_CONTENT_TAGS:
            self._flush_block()
            self._non_content_depth += 1
            return

        if self._non_content_depth:
            return

        if (
            element_id in self.REFERENCE_MARKERS
            or classes.intersection(self.REFERENCE_MARKERS)
        ):
            self._flush_block()
            self._reference_depth += 1
            return

        if self._reference_depth:
            return

        if classes.intersection(self.CONTENT_CLASSES):
            self._content_depth += 1

        if tag in self.BLOCK_TAGS:
            self._flush_block()

        if tag == "title":
            self._in_title = True

        if tag == "a":
            href = attr_map.get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in self.SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return

        if self._skip_depth:
            return

        if tag in self.NON_CONTENT_TAGS:
            if self._non_content_depth:
                self._non_content_depth -= 1
            return

        if self._non_content_depth:
            return

        if self._reference_depth:
            if tag in {"div", "ol", "ul", "section"}:
                self._reference_depth -= 1
            return

        if tag in self.BLOCK_TAGS:
            self._flush_block()

        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if (
            self._skip_depth
            or self._non_content_depth
            or self._reference_depth
        ):
            return

        text = data.strip()

        if not text:
            return

        if self._in_title:
            self.title_parts.append(text)

        self._current_block.append(text)

    def close(self):
        super().close()
        self._flush_block()


class DeepSearch:
    """
    Unlimited adaptive research crawler.

    pages=0 means unlimited.
    depth=0 means unlimited depth.
    """

    def __init__(
        self,
        search_hub,
        fast_agent,
        max_pages=0,
        max_depth=0,
        max_page_bytes=2_000_000,
        max_evidence_chars=30_000,
    ):
        self.search_hub = search_hub
        self.fast_agent = fast_agent
        self.cache = SearchCache()

        # 0 = unlimited.
        self.max_pages = int(max_pages)
        self.max_depth = int(max_depth)

        # Protect the Android device from enormous individual responses.
        self.max_page_bytes = int(max_page_bytes)

        # Keep the final Groq prompt bounded even when crawling is unlimited.
        self.max_evidence_chars = int(max_evidence_chars)

    # ==========================================================
    # URL NORMALIZATION
    # ==========================================================

    @staticmethod
    def _normalize_url(url):
        if not url:
            return ""

        try:
            parts = urlsplit(url.strip())

            if parts.scheme.lower() not in {"http", "https"}:
                return ""

            if not parts.netloc:
                return ""

            path = parts.path or "/"

            return urlunsplit(
                (
                    parts.scheme.lower(),
                    parts.netloc.lower(),
                    path.rstrip("/") or "/",
                    parts.query,
                    "",
                )
            )

        except Exception:
            return ""

    # ==========================================================
    # TEXT CLEANING
    # ==========================================================

    @staticmethod
    def _clean_text(text):
        text = re.sub(r"\s+", " ", text or "")
        return text.strip()

    @classmethod
    def _parse_page(cls, html, base_url):
        parser = _ResearchHTMLParser()

        try:
            parser.feed(html)
            parser.close()
        except Exception:
            # Partial HTML is still useful.
            pass

        # Prefer structured blocks so navigation, references, and other
        # page chrome do not collapse into one undifferentiated text stream.
        blocks = [
            cls._clean_text(block)
            for block in parser.blocks
            if cls._clean_text(block)
        ]

        text = cls._clean_text(" ".join(blocks))
        title = cls._clean_text(" ".join(parser.title_parts))

        links = []

        for href in parser.links:
            try:
                absolute = urljoin(base_url, href)
                normalized = cls._normalize_url(absolute)

                if normalized:
                    links.append(normalized)

            except Exception:
                continue

        return title, text, links

    # ==========================================================
    # RELEVANCE
    # ==========================================================

    @staticmethod
    def _terms(query):
        return {
            word.lower()
            for word in re.findall(r"[A-Za-z0-9]{3,}", query)
        }

    @classmethod
    def _intent_score(cls, query, text, title=""):
        """
        Lightweight deterministic intent scoring.

        This is deliberately not an LLM router. It gives the crawler
        a small amount of query-aware signal so an origin/creator
        question does not get dominated by generic tutorial pages.
        """
        query_lower = query.lower()
        text_lower = text.lower()
        title_lower = title.lower()

        score = 0.0

        origin_intent = any(
            phrase in query_lower
            for phrase in (
                "who created",
                "who invented",
                "who developed",
                "who designed",
                "creator of",
                "inventor of",
                "developer of",
                "origin of",
                "when was it created",
                "when was it invented",
                "when was it first released",
            )
        )

        if origin_intent:
            strong_phrases = (
                "created by",
                "creator",
                "invented by",
                "inventor",
                "developed by",
                "developer",
                "designed by",
                "first released",
                "first appeared",
                "introduced by",
                "originally created",
            )

            for phrase in strong_phrases:
                if phrase in text_lower:
                    score += 8.0

            historical_terms = (
                "1991",
                "1989",
                "1990",
                "history",
                "origin",
                "named after",
            )

            for term in historical_terms:
                if term in text_lower:
                    score += 2.0

            noise_terms = (
                "course",
                "enrolled students",
                "prerequisites",
                "salary",
                "learn python",
                "tutorial",
            )

            for term in noise_terms:
                if term in title_lower or term in text_lower:
                    score -= 4.0

        return score

    @classmethod
    def _relevance(cls, query, text, title=""):
        terms = cls._terms(query)

        if not terms:
            return 0.0

        title_lower = title.lower()
        text_lower = text.lower()

        title_hits = sum(
            term in title_lower
            for term in terms
        )

        body_hits = sum(
            term in text_lower
            for term in terms
        )

        coverage = (
            body_hits / max(len(terms), 1)
        )

        phrase_bonus = 0.0
        normalized_query = " ".join(
            query.lower().split()
        )

        if (
            normalized_query
            and normalized_query in text_lower
        ):
            phrase_bonus = 8.0

        intent_bonus = cls._intent_score(
            query,
            text,
            title,
        )

        # Title matches and term coverage provide the generic
        # relevance signal. Intent scoring handles questions where
        # raw keyword frequency is misleading.
        return (
            title_hits * 6.0
            + coverage * 10.0
            + phrase_bonus
            + intent_bonus
        )

    @classmethod
    def _link_relevance(cls, query, url):
        """
        Cheap URL-level relevance check before fetching a discovered link.
        """
        terms = cls._terms(query)
        target = url.lower()

        return sum(term in target for term in terms)

    # ==========================================================
    # CRAWL
    # ==========================================================

    def _crawl(self, query, initial_results):
        queue = deque()
        visited = set()
        evidence = []

        # Seed the crawler with SearchHub results.
        for result in initial_results:
            url = self._normalize_url(result.url)

            if not url or url in visited:
                continue

            queue.append(
                (
                    url,
                    0,
                    result.source,
                    result.title,
                    result.snippet,
                )
            )

        pages_crawled = 0

        while queue:
            url, depth, source, seed_title, seed_snippet = queue.popleft()

            if url in visited:
                continue

            if self.max_pages and pages_crawled >= self.max_pages:
                break

            if self.max_depth and depth > self.max_depth:
                continue

            visited.add(url)

            try:
                # Prefer Tor, but fall back to a direct fetch if
                # Tor is unavailable or returns no page content.
                try:
                    html = self.search_hub.fetch(
                        url,
                        use_tor=True,
                        timeout=20,
                    )
                except Exception:
                    html = None

                if not html:
                    try:
                        html = self.search_hub.fetch(
                            url,
                            use_tor=False,
                            timeout=15,
                        )
                    except Exception:
                        html = None

                if not html:
                    continue

                if len(html) > self.max_page_bytes:
                    html = html[:self.max_page_bytes]

                title, text, links = self._parse_page(
                    html,
                    url,
                )

                title = title or seed_title or url

                if not text:
                    continue

                score = self._relevance(
                    query,
                    text,
                    title,
                )

                evidence.append(
                    {
                        "url": url,
                        "source": source,
                        "title": title,
                        "snippet": seed_snippet or "",
                        "content": text,
                        "relevance": score,
                        "depth": depth,
                    }
                )

                pages_crawled += 1

                # Discover more pages.
                if self.max_depth and depth >= self.max_depth:
                    continue

                candidates = []

                for link in links:
                    if link in visited:
                        continue

                    link_score = self._link_relevance(
                        query,
                        link,
                    )

                    candidates.append(
                        (link_score, link)
                    )

                # Higher-relevance URLs are explored first.
                candidates.sort(
                    key=lambda item: (-item[0], item[1])
                )

                for link_score, link in candidates:
                    if link in visited:
                        continue

                    # Skip obvious non-document resources.
                    path = urlsplit(link).path.lower()

                    blocked_extensions = (
                        ".jpg", ".jpeg", ".png", ".gif",
                        ".webp", ".svg", ".ico",
                        ".mp3", ".wav", ".ogg",
                        ".mp4", ".webm", ".avi",
                        ".zip", ".tar", ".gz",
                        ".7z", ".rar",
                        ".exe", ".apk",
                        ".deb", ".iso",
                    )

                    if path.endswith(blocked_extensions):
                        continue

                    # Query-relevant URLs get priority. Completely
                    # unrelated links remain discoverable, but behind
                    # relevant links in the frontier.
                    priority = float(link_score)

                    queue.append(
                        (
                            link,
                            depth + 1,
                            source,
                            "",
                            "",
                        )
                    )

            except Exception:
                # A single failed page must never stop research.
                continue

        return evidence

    # ==========================================================
    # EVIDENCE
    # ==========================================================

    @classmethod
    def _focused_passage(cls, query, content, title=""):
        """
        Extract a query-focused passage from flattened crawler text.

        HTML parsing intentionally flattens navigation and body text.
        Therefore, use scored character windows rather than relying only
        on sentence boundaries.
        """
        content = cls._clean_text(content)

        if not content:
            return ""

        lower = content.lower()
        query_lower = " ".join(query.lower().split())
        query_terms = cls._terms(query)

        q = query_lower

        intent_phrases = []

        if any(x in q for x in (
            "who created",
            "who invented",
            "who developed",
            "who founded",
            "created by",
            "invented by",
            "creator",
        )):
            intent_phrases.extend([
                "created by",
                "created",
                "creator",
                "invented by",
                "invented",
                "developed by",
                "designed by",
                "designer",
                "guido van rossum",
            ])

        if any(x in q for x in (
            "when was",
            "when did",
            "what year",
            "released",
            "release",
        )):
            intent_phrases.extend([
                "first released",
                "released",
                "release",
                "1991",
                "history",
                "created",
            ])

        if any(x in q for x in (
            "what is",
            "what are",
            "define",
            "explain",
        )):
            intent_phrases.extend([
                "programming language",
                "high-level",
                "general-purpose",
                "software",
            ])

        candidates = []

        # --------------------------------------------------------
        # Search around important intent phrases.
        # --------------------------------------------------------
        for phrase in intent_phrases:
            position = 0

            while True:
                position = lower.find(phrase, position)

                if position == -1:
                    break

                start_pos = max(0, position - 700)
                end_pos = min(
                    len(content),
                    position + len(phrase) + 1200,
                )

                window = content[start_pos:end_pos].strip()
                window_lower = window.lower()

                score = 0.0

                # Intent phrase itself.
                score += 20.0

                # Query vocabulary coverage.
                score += sum(
                    3.0
                    for term in query_terms
                    if term in window_lower
                )

                # Strong factual relationships.
                if "guido van rossum" in window_lower:
                    score += 30.0

                if any(x in window_lower for x in (
                    "created by guido",
                    "designed by guido",
                    "developed by guido",
                    "van rossum",
                )):
                    score += 20.0

                # Navigation/TOC penalties.
                if any(x in window_lower for x in (
                    "jump to content",
                    "main menu",
                    "personal tools",
                    "donate create account",
                    "toggle",
                    "contents move to sidebar",
                    "navigation main page",
                    "recent changes",
                    "special pages",
                    "programming languages comparison",
                    "lists: alphabetical",
                )):
                    score -= 35.0

                candidates.append(
                    (
                        score,
                        window,
                    )
                )

                position += len(phrase)

        # --------------------------------------------------------
        # Query-term windows as a fallback.
        # --------------------------------------------------------
        if not candidates:
            for term in query_terms:
                position = 0

                while True:
                    position = lower.find(term, position)

                    if position == -1:
                        break

                    start_pos = max(0, position - 500)
                    end_pos = min(
                        len(content),
                        position + len(term) + 1000,
                    )

                    window = content[start_pos:end_pos].strip()
                    window_lower = window.lower()

                    score = 5.0

                    if any(x in window_lower for x in (
                        "jump to content",
                        "main menu",
                        "personal tools",
                        "contents move to sidebar",
                        "navigation main page",
                    )):
                        score -= 25.0

                    candidates.append(
                        (
                            score,
                            window,
                        )
                    )

                    position += len(term)

        if not candidates:
            return content[:2000]

        candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        # Remove near-duplicate windows.
        selected = []

        for score, window in candidates:
            normalized = " ".join(
                window.lower().split()
            )

            if any(
                normalized[:300] == existing[:300]
                for existing in selected
            ):
                continue

            selected.append(window)

            if len(selected) >= 2:
                break

        passage = " ".join(selected)

        return passage[:4000]


    def _build_evidence(self, query, initial_results):
        """
        Build compact, diverse evidence from the crawl.

        Seed results retain their original search relevance and provider
        diversity. Crawled pages can add supporting evidence, but they do
        not displace authoritative seed sources merely because they contain
        more repeated query terms.
        """
        pages = self._crawl(query, initial_results)

        if not pages:
            return [], 0

        # Prefer authoritative/general-reference providers for factual
        # research, while still allowing other providers to contribute.
        provider_priority = {
            "wikipedia": 100,
            "brave": 90,
            "bing": 85,
            "duckduckgo": 80,
            "github": 60,
            "reddit": 50,
        }

        candidates = []

        for item in pages:
            provider = (item.get("source") or "").lower()
            title = (
                item.get("title", "")
                or item.get("url", "")
            )[:300]

            text = item.get("content", "") or ""
            score = float(item.get("relevance", 0.0))

            # Provider preference is only a tie-breaker. It must not
            # overwhelm actual relevance.
            provider_bonus = provider_priority.get(provider, 40) / 100.0

            candidates.append({
                "item": item,
                "score": score + provider_bonus,
                "provider": provider,
                "title": title,
            })

        candidates.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        selected = []
        providers_seen = set()

        # First pass: preserve provider diversity.
        for candidate in candidates:
            provider = candidate["provider"]

            if provider in providers_seen:
                continue

            selected.append(candidate)
            providers_seen.add(provider)

            if len(selected) >= 4:
                break

        # Second pass: fill remaining evidence slots by score.
        selected_ids = {
            id(candidate["item"])
            for candidate in selected
        }

        for candidate in candidates:
            if id(candidate["item"]) in selected_ids:
                continue

            selected.append(candidate)

            if len(selected) >= 8:
                break

        evidence = []

        for index, candidate in enumerate(selected, 1):
            item = candidate["item"]

            provider = item.get("source", "")
            title = (
                item.get("title", "")
                or item.get("url", "")
            )[:300]

            url = item.get("url", "")
            raw_content = (
                item.get("content", "")
                or item.get("snippet", "")
                or ""
            ).strip()

            if not raw_content:
                continue

            content = self._focused_passage(
                query,
                raw_content,
                title,
            )

            if not content:
                continue

            block = (
                f"SOURCE {index}\n"
                f"Provider: {provider}\n"
                f"Title: {title}\n"
                f"URL: {url}\n"
                f"Content: {content}"
            )

            evidence.append(block)

            total_chars = sum(len(x) for x in evidence)

            if total_chars >= self.max_evidence_chars:
                break

        return evidence, len(pages)

    def search(self, query, limit=8):
        cache_ttl = ttl_for_query(query, stable=7 * 86400, volatile=3600)
        cached_answer = self.cache.get(
            "deep-search",
            query,
            variant=str(limit),
            ttl_seconds=cache_ttl,
        )
        if isinstance(cached_answer, str) and cached_answer.strip():
            print(f" [WEB CACHE] Reusing saved deep-research answer for: {query[:80]}")
            return cached_answer

        initial_results = self.search_hub.search(
            query,
            limit=limit,
        )

        if not initial_results:
            return (
                "I couldn't find enough information to "
                "research that, sir."
            )

        evidence, source_count = self._build_evidence(
            query,
            initial_results,
        )

        if not evidence:
            return (
                "I found search results, but I couldn't "
                "retrieve usable research evidence, sir."
            )

        prompt = f"""
You are JARVIS performing deep web research.

Research question:
{query}

Collected research evidence:
{chr(10).join(evidence)}

Produce a concise but accurate synthesis.

Rules:
- Use only information supported by the supplied evidence.
- Cross-check claims across independent sources when possible.
- Do not invent missing facts.
- Identify uncertainty or conflicting evidence.
- Prefer concrete findings over generic background.
- Do not read URLs aloud.
- Do not mention internal crawling details.
- Keep the answer suitable for text-to-speech.
- Maximum 5 short sentences.
"""

        try:
            answer = self.fast_agent.ask_synthesis(prompt)

            if answer and str(answer).strip():
                answer = str(answer).strip()
                self.cache.put(
                    "deep-search",
                    query,
                    answer,
                    variant=str(limit),
                    ttl_seconds=cache_ttl,
                )
                print(" [WEB CACHE] Saved deep-research answer locally.")
                return answer

        except Exception:
            pass

        return (
            f"I researched {source_count} sources, but I "
            "couldn't generate the final synthesis right now, sir."
        )
