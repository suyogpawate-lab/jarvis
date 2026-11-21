"""Low-overhead, permission-aware social integrations for JARVIS.

All credentials are read from the process environment (normally loaded from the
private project .env). This module intentionally uses requests already required
by JARVIS; it adds no runtime dependency.
"""
import os
import re
import time
from urllib.parse import quote

import requests

from tools.registry import registry

TIMEOUT = 12
MAX_ITEMS = 30
GRAPH_VERSION = os.getenv("JARVIS_META_GRAPH_VERSION", "v26.0")


def _request(method, url, *, token=None, params=None, json_body=None, headers=None):
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    response = requests.request(
        method, url, headers=h, params=params, data=json_body, timeout=TIMEOUT
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message") or response.text
        except Exception:
            detail = response.text
        raise RuntimeError("HTTP %s: %s" % (response.status_code, str(detail)[:350]))
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


def _env(key):
    return os.getenv(key, "").strip()


def _connected_accounts():
    return {
        "github": bool(_env("JARVIS_GITHUB_TOKEN")),
        "reddit": bool(_env("JARVIS_REDDIT_ACCESS_TOKEN")),
        "youtube": bool(_env("JARVIS_YOUTUBE_ACCESS_TOKEN")),
        "facebook_page": bool((_env("JARVIS_FACEBOOK_PAGE_ACCESS_TOKEN") or _env("JARVIS_META_ACCESS_TOKEN")) and _env("JARVIS_FACEBOOK_PAGE_ID")),
        "instagram_professional": bool((_env("JARVIS_INSTAGRAM_ACCESS_TOKEN") or _env("JARVIS_META_ACCESS_TOKEN")) and _env("JARVIS_INSTAGRAM_USER_ID")),
        "linkedin": bool(_env("JARVIS_LINKEDIN_ACCESS_TOKEN")),
    }


def _status(_args):
    connected = _connected_accounts()
    details = {
        "github": "Personal token: notifications and repository starring.",
        "reddit": "OAuth token: read-only feed review. Voting is deliberately not automated.",
        "youtube": "OAuth token: subscription feed and explicit like/unlike actions.",
        "facebook_page": "Page token + Page ID: Page feed and Page publishing; personal profile feed is not exposed.",
        "instagram_professional": "Professional account token + IG user ID: media review and image publishing; personal consumer accounts are not supported by the official API.",
        "linkedin": "OAuth token: access depends on approved member/organization permissions; reading member social data is restricted.",
    }
    return {
        "ok": True,
        "accounts": [
            {"platform": name, "connected": bool(connected[name]), "capability": details[name]}
            for name in connected
        ],
        "note": "Connected means credentials are configured, not that the provider has validated them. Use a review/action to verify access.",
    }


def _item(platform, title, text, url, created=None, source=None):
    return {
        "platform": platform,
        "title": str(title or "(untitled)")[:180],
        "summary": re.sub(r"\s+", " ", str(text or "")).strip()[:500],
        "url": str(url or ""),
        "created": created,
        "source": source or platform,
    }


def _collect_github(limit):
    token = _env("JARVIS_GITHUB_TOKEN")
    if not token:
        return []
    data = _request("GET", "https://api.github.com/notifications",
                    token=token, params={"all": "false", "per_page": min(limit, 50)},
                    headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    out = []
    for row in data if isinstance(data, list) else []:
        subject = row.get("subject") or {}
        repo = row.get("repository") or {}
        out.append(_item("github", subject.get("title"), subject.get("type"),
                         subject.get("url") or repo.get("html_url"),
                         row.get("updated_at"), repo.get("full_name")))
    return out


def _collect_reddit(limit):
    token = _env("JARVIS_REDDIT_ACCESS_TOKEN")
    if not token:
        return []
    ua = _env("JARVIS_REDDIT_USER_AGENT") or "JARVIS/1.0 (personal feed reader)"
    data = _request("GET", "https://oauth.reddit.com/best",
                    token=token, params={"limit": min(limit, 100), "raw_json": 1, "include_over_18": "0"},
                    headers={"User-Agent": ua})
    out = []
    for child in (data.get("data") or {}).get("children", []):
        post = child.get("data") or {}
        if post.get("over_18"):
            continue
        permalink = post.get("permalink", "")
        out.append(_item("reddit", post.get("title"), post.get("selftext") or ("r/" + str(post.get("subreddit", ""))),
                         "https://www.reddit.com" + permalink if permalink.startswith("/") else post.get("url"),
                         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(post.get("created_utc", 0))),
                         "r/" + str(post.get("subreddit", ""))))
    return out


def _collect_instagram(limit):
    token, user_id = (_env("JARVIS_INSTAGRAM_ACCESS_TOKEN") or _env("JARVIS_META_ACCESS_TOKEN")), _env("JARVIS_INSTAGRAM_USER_ID")
    if not token or not user_id:
        return []
    host = _env("JARVIS_INSTAGRAM_API_HOST") or "https://graph.instagram.com"
    data = _request("GET", "%s/%s/%s/media" % (host.rstrip("/"), GRAPH_VERSION, quote(user_id, safe="")),
                    token=token, params={"fields": "id,caption,media_type,permalink,timestamp", "limit": min(limit, 50)})
    return [_item("instagram", (x.get("caption") or x.get("media_type") or "Instagram media").splitlines()[0],
                  x.get("caption"), x.get("permalink"), x.get("timestamp"), x.get("media_type"))
            for x in data.get("data", [])]


def _collect_facebook(limit):
    token, page_id = (_env("JARVIS_FACEBOOK_PAGE_ACCESS_TOKEN") or _env("JARVIS_META_ACCESS_TOKEN")), _env("JARVIS_FACEBOOK_PAGE_ID")
    if not token or not page_id:
        return []
    data = _request("GET", "https://graph.facebook.com/%s/%s/feed" % (GRAPH_VERSION, quote(page_id, safe="")),
                    token=token, params={"fields": "message,permalink_url,created_time,from", "limit": min(limit, 50)})
    return [_item("facebook_page", (x.get("message") or "Facebook Page post").splitlines()[0],
                  x.get("message"), x.get("permalink_url"), x.get("created_time"),
                  (x.get("from") or {}).get("name")) for x in data.get("data", [])]


def _collect_linkedin(limit):
    token, author = _env("JARVIS_LINKEDIN_ACCESS_TOKEN"), _env("JARVIS_LINKEDIN_PERSON_URN")
    if not token or not author:
        return []
    version = _env("JARVIS_LINKEDIN_VERSION") or "202610"
    data = _request("GET", "https://api.linkedin.com/rest/posts",
                    token=token, params={"q": "author", "author": author, "count": min(limit, 20)},
                    headers={"LinkedIn-Version": version, "X-Restli-Protocol-Version": "2.0.0"})
    out = []
    for row in data.get("elements", []):
        commentary = row.get("commentary") or ""
        urn = row.get("id") or ""
        out.append(_item("linkedin", commentary[:140] or "LinkedIn post", commentary,
                         "https://www.linkedin.com/feed/update/" + urn if urn else "",
                         row.get("createdAt"), author))
    return out


def _collect_youtube(limit):
    token = _env("JARVIS_YOUTUBE_ACCESS_TOKEN")
    if not token:
        return []
    headers = {"Accept": "application/json"}
    subs = _request("GET", "https://www.googleapis.com/youtube/v3/subscriptions",
                    token=token, params={"part": "snippet,contentDetails", "mine": "true",
                                          "maxResults": min(limit, 25)},
                    headers=headers)
    channels = []
    for row in subs.get("items", []):
        snippet = row.get("snippet") or {}
        details = row.get("contentDetails") or {}
        channel_id = (snippet.get("resourceId") or {}).get("channelId")
        uploads = (details.get("relatedPlaylists") or {}).get("uploads")
        if channel_id and uploads:
            channels.append((snippet.get("title") or "YouTube channel", uploads))
    out = []
    for channel, playlist in channels[:min(limit, 4)]:
        data = _request("GET", "https://www.googleapis.com/youtube/v3/playlistItems",
                        token=token, params={"part": "snippet,contentDetails", "playlistId": playlist, "maxResults": 2},
                        headers=headers)
        for row in data.get("items", []):
            sn = row.get("snippet") or {}
            vid = (row.get("contentDetails") or {}).get("videoId")
            if not vid:
                continue
            out.append(_item("youtube", sn.get("title"), sn.get("description"),
                             "https://www.youtube.com/watch?v=" + vid,
                             sn.get("publishedAt"), channel))
    return out


def _rank(items, topic):
    terms = [x.lower() for x in re.findall(r"[a-zA-Z0-9+#.-]{2,}", topic or "")]
    seen, ranked = set(), []
    for item in items:
        key = item.get("url") or (item["platform"] + item["title"])
        if key in seen:
            continue
        seen.add(key)
        blob = (item["title"] + " " + item["summary"] + " " + str(item["source"])).lower()
        score = sum(3 if term in item["title"].lower() else 1 for term in terms if term in blob)
        item["relevance"] = score
        ranked.append(item)
    ranked.sort(key=lambda x: (x["relevance"], x.get("created") or ""), reverse=True)
    return ranked


def _review(args):
    limit = max(1, min(int(args.get("limit", 15)), MAX_ITEMS))
    topic = str(args.get("topic") or "").strip()
    selected = args.get("platforms") or ["github", "reddit", "youtube", "instagram", "facebook", "linkedin"]
    allowed = {"github", "reddit", "youtube", "instagram", "facebook", "linkedin"}
    selected = [p for p in selected if p in allowed]
    collectors = {
        "github": _collect_github, "reddit": _collect_reddit,
        "youtube": _collect_youtube, "instagram": _collect_instagram,
        "facebook": _collect_facebook, "linkedin": _collect_linkedin,
    }
    items, errors = [], []
    for platform in selected:
        try:
            items.extend(collectors[platform](limit))
        except Exception as exc:
            errors.append({"platform": platform, "error": str(exc)[:300]})
    ranked = _rank(items, topic)[:limit]
    return {
        "ok": True,
        "topic": topic or "general",
        "count": len(ranked),
        "items": ranked,
        "errors": errors,
        "session_limit": limit,
        "note": "Finite digest only. No automatic likes, votes, comments, follows, reposts, or publishing. Reddit posts marked mature are filtered out.",
    }


def _manage(args):
    if args.get("confirmed") is not True:
        return {"ok": False, "error": "This action requires a direct user request and confirmed=true."}
    platform, action = args.get("platform", ""), args.get("action", "")
    target, text = str(args.get("target") or "").strip(), str(args.get("text") or "").strip()

    if platform == "github" and action in ("star", "unstar"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", target):
            return {"ok": False, "error": "target must be a repository in owner/name format."}
        token = _env("JARVIS_GITHUB_TOKEN")
        if not token:
            return {"ok": False, "error": "Set JARVIS_GITHUB_TOKEN in the private .env first."}
        _request("PUT" if action == "star" else "DELETE",
                 "https://api.github.com/user/starred/" + target, token=token,
                 headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        return {"ok": True, "result": "Repository %s: %s" % (target, action + "red" if action == "star" else "unstarred")}

    if platform == "youtube" and action in ("like", "unlike"):
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", target)
        video_id = match.group(1) if match else target
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return {"ok": False, "error": "target must be a YouTube video URL or 11-character video ID."}
        token = _env("JARVIS_YOUTUBE_ACCESS_TOKEN")
        if not token:
            return {"ok": False, "error": "Set JARVIS_YOUTUBE_ACCESS_TOKEN with the youtube.force-ssl scope."}
        _request("POST", "https://www.googleapis.com/youtube/v3/videos/rate",
                 token=token, params={"id": video_id, "rating": "like" if action == "like" else "none"})
        return {"ok": True, "result": "YouTube rating updated for " + video_id}

    if platform == "facebook" and action == "publish":
        token, page_id = _env("JARVIS_META_ACCESS_TOKEN"), _env("JARVIS_FACEBOOK_PAGE_ID")
        if not token or not page_id:
            return {"ok": False, "error": "Configure a Page access token and JARVIS_FACEBOOK_PAGE_ID."}
        if not text:
            return {"ok": False, "error": "text is required for publishing."}
        result = _request("POST", "https://graph.facebook.com/%s/%s/feed" % (GRAPH_VERSION, quote(page_id, safe="")),
                          token=token, json_body={"message": text})
        return {"ok": True, "result": result}

    if platform == "linkedin" and action == "publish":
        token, author = _env("JARVIS_LINKEDIN_ACCESS_TOKEN"), _env("JARVIS_LINKEDIN_PERSON_URN")
        if not token or not author:
            return {"ok": False, "error": "Configure JARVIS_LINKEDIN_ACCESS_TOKEN and JARVIS_LINKEDIN_PERSON_URN."}
        if not text:
            return {"ok": False, "error": "text is required for LinkedIn publishing."}
        version = _env("JARVIS_LINKEDIN_VERSION") or "202610"
        response = requests.post(
            "https://api.linkedin.com/rest/posts",
            headers={"Authorization": "Bearer " + token, "LinkedIn-Version": version,
                     "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"},
            json={"author": author, "commentary": text, "visibility": "PUBLIC",
                  "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                                   "thirdPartyDistributionChannels": []},
                  "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False},
            timeout=TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError("LinkedIn HTTP %s: %s" % (response.status_code, response.text[:300]))
        return {"ok": True, "result": {"id": response.headers.get("x-restli-id") or response.text[:300]}}

    if platform == "instagram" and action == "publish_image":
        token, user_id = _env("JARVIS_META_ACCESS_TOKEN"), _env("JARVIS_INSTAGRAM_USER_ID")
        media_url = str(args.get("media_url") or "").strip()
        if not token or not user_id:
            return {"ok": False, "error": "Configure a professional-account token and JARVIS_INSTAGRAM_USER_ID."}
        if not media_url.startswith("https://") or not text:
            return {"ok": False, "error": "A public HTTPS media_url and caption text are required."}
        host = _env("JARVIS_INSTAGRAM_API_HOST") or "https://graph.instagram.com"
        base = "%s/%s/%s" % (host.rstrip("/"), GRAPH_VERSION, quote(user_id, safe=""))
        container = _request("POST", base + "/media", token=token,
                             json_body={"image_url": media_url, "caption": text})
        creation_id = container.get("id")
        if not creation_id:
            return {"ok": False, "error": "Meta did not return a media container ID."}
        result = _request("POST", base + "/media_publish", token=token,
                          json_body={"creation_id": creation_id})
        return {"ok": True, "result": result}

    if platform == "reddit" and action in ("upvote", "downvote", "vote"):
        return {"ok": False, "error": "JARVIS will not automate Reddit voting. Choose votes yourself in Reddit."}
    return {"ok": False, "error": "Unsupported platform/action combination. Available actions: GitHub star/unstar, YouTube like/unlike, Facebook Page publish, LinkedIn member publish, Instagram professional image publish."}


def register():
    """Expose natural-language social tools through JARVIS's shared registry."""
    registry.unregister_prefix("social_")
    registry.register(
        "social_accounts",
        "Show which social accounts have credentials configured and explain each account's supported access boundaries. Use for questions about connected social accounts or account compatibility.",
        {"type": "object", "properties": {}, "required": []},
        _status,
    )
    registry.register(
        "social_review",
        "Create a finite, ranked social-feed digest. Read recent GitHub notifications, Reddit best posts, YouTube subscription uploads, Instagram professional media, Facebook Page posts, and LinkedIn member posts where the configured OAuth scopes allow it. Filter Reddit mature posts, deduplicate, rank against the user's topic, and return original links. Use when the user wants a feed review, catch-up, research scan, or a replacement for doomscrolling. Never engage with content from this read tool.",
        {"type": "object", "properties": {
            "topic": {"type": "string", "description": "Optional interest/topic to rank items against."},
            "platforms": {"type": "array", "items": {"type": "string", "enum": ["github", "reddit", "youtube", "instagram", "facebook", "linkedin"]}, "description": "Optional platforms to review; omit for all configured platforms."},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS, "description": "Maximum total digest items; defaults to 15."}
        }, "required": []},
        _review,
    )
    registry.register(
        "social_manage",
        "Perform a specifically requested social-account action. Only use when the user directly asks to perform the exact action; set confirmed=true only for that explicit request. Supported: GitHub star/unstar a repository; YouTube like/unlike a video; publish text to a Facebook Page or LinkedIn member profile; publish an image with caption to an Instagram professional account. Do not infer a desire to engage from feed content. Never automate Reddit votes.",
        {"type": "object", "properties": {
            "platform": {"type": "string", "enum": ["github", "youtube", "facebook", "linkedin", "instagram"]},
            "action": {"type": "string", "enum": ["star", "unstar", "like", "unlike", "publish", "publish_image"]},
            "target": {"type": "string", "description": "GitHub owner/repository or YouTube video URL/ID."},
            "text": {"type": "string", "description": "Post text or caption for publishing."},
            "media_url": {"type": "string", "description": "Public HTTPS image URL for Instagram image publishing."},
            "confirmed": {"type": "boolean", "description": "Must be true only when the user explicitly requested this exact action."}
        }, "required": ["platform", "action", "confirmed"]},
        _manage,
    )
    return 3
