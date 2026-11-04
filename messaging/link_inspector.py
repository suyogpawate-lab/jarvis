"""Safe inspection of publicly reachable web pages for WhatsApp link context.

Only HTTP(S) pages resolving to public IP addresses are fetched. Redirects are
validated hop-by-hop; page content is evidence, never executable instructions.
"""
import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.parts = []
        self.description = ""
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag.lower() == "meta" and attrs.get("name", "").lower() in {
            "description", "og:description"
        }:
            self.description = attrs.get("content", "")[:2000]

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title.append(text)
        elif not self._skip:
            self.parts.append(text)


def _public_host(host):
    if not host:
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
        return bool(addresses) and all(
            ipaddress.ip_address(address).is_global for address in addresses
        )
    except (OSError, ValueError):
        return False


def inspect_public_page(url, max_bytes=2_000_000):
    """Extract readable text from a public HTML page with SSRF protections."""
    try:
        parsed = urlparse(str(url).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return {"ok": False, "error": "Only public HTTP(S) links are supported."}
        if parsed.username or parsed.password:
            return {"ok": False, "error": "Links containing credentials are not supported."}
        current = url
        response = None
        for _ in range(6):
            parsed = urlparse(current)
            if parsed.scheme not in {"http", "https"} or not _public_host(parsed.hostname):
                return {"ok": False, "url": current, "error": "The link or redirect did not resolve to a public host."}
            response = requests.get(
                current, timeout=(5, 12), stream=True, allow_redirects=False,
                headers={"User-Agent": "Mozilla/5.0 (compatible; JARVIS-LinkReader/1.0)"},
            )
            if response.is_redirect:
                target = response.headers.get("Location")
                response.close()
                if not target:
                    return {"ok": False, "error": "The site returned an invalid redirect."}
                current = urljoin(current, target)
                continue
            break
        else:
            return {"ok": False, "error": "Too many redirects."}

        if response is None:
            return {"ok": False, "error": "No response from the website."}
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            response.close()
            return {"ok": False, "url": current, "error": f"Unsupported page content type: {content_type or 'unknown'}."}
        chunks = []
        size = 0
        for chunk in response.iter_content(65536):
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                break
            chunks.append(chunk)
        encoding = response.encoding or "utf-8"
        response.close()
        source = b"".join(chunks).decode(encoding, errors="replace")
        parser = _PageText()
        parser.feed(source)
        text = "\n".join(parser.parts)
        return {
            "ok": True, "url": current,
            "title": html.unescape(" ".join(parser.title))[:300],
            "description": html.unescape(parser.description)[:1800],
            "text": text[:12000],
            "truncated": size > max_bytes,
            "content_access": "page_text",
        }
    except Exception as exc:
        return {"ok": False, "url": str(url)[:1000],
                "error": f"Public page inspection failed: {type(exc).__name__}."}
