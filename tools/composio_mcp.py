"""Optional Composio Sessions -> hosted Streamable HTTP MCP integration.

No SDK or extra dependency is required: JARVIS already depends on requests.
Only read-only app tools plus Composio search/connection-management meta tools
are exposed. Write actions remain unavailable over this transport until JARVIS
has a local approval-aware execution path.
"""

import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

import requests

from tools import mcp_client
from tools.registry import registry

ROOT = Path(__file__).resolve().parent.parent
API_BASE = os.getenv(
    "JARVIS_COMPOSIO_API_BASE", "https://backend.composio.dev"
).rstrip("/")
SESSION_FILE = Path(os.getenv(
    "JARVIS_COMPOSIO_SESSION_FILE",
    str(ROOT / "data" / "composio_session.json"),
)).expanduser()
API_TIMEOUT = max(5, min(int(os.getenv("JARVIS_COMPOSIO_TIMEOUT", "25")), 60))
_ALLOWED_META_TOOLS = {
    "COMPOSIO_SEARCH_TOOLS",
    "COMPOSIO_MANAGE_CONNECTIONS",
    "COMPOSIO_MULTI_EXECUTE_TOOL",
}
_PROTOCOL_VERSION = "2025-03-26"


def _log(message):
    mcp_client._log_failure("composio", message)


def _toolkits():
    raw = os.getenv(
        "JARVIS_COMPOSIO_TOOLKITS",
        "instagram,github,youtube,reddit,linkedin,facebook",
    )
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    # Keep the session narrow and reject malformed toolkit names.
    return list(dict.fromkeys(
        value for value in values
        if value.replace("_", "").isalnum()
    ))[:12]


def _valid_mcp_url(value):
    parsed = urlparse(str(value or ""))
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and (host == "composio.dev" or host.endswith(".composio.dev"))
        and bool(parsed.path)
    )


def _load_or_create_session(api_key, user_id):
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

    saved_id = ""
    try:
        saved = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        saved_id = str(saved.get("session_id") or "").strip()
    except (OSError, ValueError, AttributeError):
        pass

    if saved_id:
        response = requests.get(
            f"{API_BASE}/api/v3.1/tool_router/session/{saved_id}",
            headers=headers,
            timeout=API_TIMEOUT,
            allow_redirects=False,
        )
        if response.status_code == 200:
            data = response.json()
            mcp = data.get("mcp") or {}
            if _valid_mcp_url(mcp.get("url")):
                return saved_id, mcp["url"]
        elif response.status_code not in (404, 410):
            detail = " ".join(response.text.split())[:220]
            raise RuntimeError(
                f"Could not resume Composio session (HTTP {response.status_code})"
                + (f": {detail}" if detail else "")
            )

    body = {
        "user_id": user_id,
        "toolkits": {"enable": _toolkits()},
        "tags": {"enable": ["readOnlyHint"]},
        "manage_connections": {"enable": True},
        "experimental": {"no_elicitation_support_fallback": "deny"},
    }
    response = requests.post(
        f"{API_BASE}/api/v3.1/tool_router/session",
        headers={**headers, "Content-Type": "application/json"},
        json=body,
        timeout=API_TIMEOUT,
        allow_redirects=False,
    )
    if response.status_code not in (200, 201):
        detail = " ".join(response.text.split())[:300]
        raise RuntimeError(
            f"Composio session creation failed (HTTP {response.status_code})"
            + (f": {detail}" if detail else "")
        )

    data = response.json()
    session_id = str(data.get("session_id") or "").strip()
    mcp_url = (data.get("mcp") or {}).get("url")
    if not session_id or not _valid_mcp_url(mcp_url):
        raise RuntimeError("Composio did not return a valid hosted MCP session.")

    temp = SESSION_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    temp.replace(SESSION_FILE)
    try:
        SESSION_FILE.chmod(0o600)
    except OSError:
        pass
    return session_id, mcp_url


class ComposioHTTPMCP:
    """Small Streamable HTTP MCP client; supports JSON and SSE responses."""

    def __init__(self, name, url, api_key):
        self.name = name
        self.url = url
        self.allow = None
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        self._request_id = 0
        self._protocol = _PROTOCOL_VERSION
        self._mcp_session_id = None

    def _next_id(self):
        self._request_id += 1
        return self._request_id

    @staticmethod
    def _decode_response(response):
        if response.status_code == 202 or not response.content:
            return {}
        if response.status_code < 200 or response.status_code >= 300:
            detail = " ".join(response.text.split())[:240]
            raise RuntimeError(
                f"Composio MCP HTTP {response.status_code}"
                + (f": {detail}" if detail else "")
            )

        content_type = response.headers.get("Content-Type", "").lower()
        if "json" in content_type:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("error"):
                raise RuntimeError(str(payload["error"])[:240])
            return payload

        # Streamable HTTP may return a single JSON-RPC message as an SSE event.
        data_lines = []
        for line in response.text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif not line.strip() and data_lines:
                raw = "\n".join(data_lines)
                data_lines = []
                try:
                    payload = json.loads(raw)
                    if isinstance(payload, dict):
                        if payload.get("error"):
                            raise RuntimeError(str(payload["error"])[:240])
                        return payload
                except ValueError:
                    continue
        if data_lines:
            try:
                payload = json.loads("\n".join(data_lines))
                if isinstance(payload, dict):
                    if payload.get("error"):
                        raise RuntimeError(str(payload["error"])[:240])
                    return payload
            except ValueError:
                pass
        raise RuntimeError("Composio MCP returned an unrecognised response.")

    def _post(self, message, timeout=API_TIMEOUT):
        headers = {"MCP-Protocol-Version": self._protocol}
        if self._mcp_session_id:
            headers["MCP-Session-Id"] = self._mcp_session_id
        response = self.session.post(
            self.url,
            json=message,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
        session_id = response.headers.get("MCP-Session-Id")
        if session_id:
            self._mcp_session_id = session_id
        return self._decode_response(response)

    def request(self, method, params=None, timeout=API_TIMEOUT):
        request_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        result = self._post(payload, timeout=timeout)
        if result.get("error"):
            error = result["error"]
            raise RuntimeError(str(error.get("message", error))[:240])
        if result.get("id") not in (None, request_id):
            raise RuntimeError("Composio MCP response ID did not match request.")
        return result.get("result") or {}

    def notify(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._post(payload)

    def start(self):
        result = self.request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "jarvis", "version": "1.0"},
        })
        self._protocol = result.get("protocolVersion") or _PROTOCOL_VERSION
        self.notify("notifications/initialized")

    def list_tools(self, timeout=API_TIMEOUT):
        tools = []
        cursor = None
        for _ in range(10):
            params = {"cursor": cursor} if cursor else {}
            result = self.request("tools/list", params, timeout=timeout)
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, tool_name, arguments):
        result = self.request(
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
            timeout=max(API_TIMEOUT, 45),
        )
        parts = []
        for item in result.get("content", []):
            kind = item.get("type")
            if kind == "text":
                parts.append(str(item.get("text", "")))
            elif kind in ("image", "audio", "resource"):
                parts.append(f"[{kind} content omitted by lightweight MCP adapter]")
        output = "\n".join(parts)[:mcp_client.MAX_RESULT_CHARS]
        if result.get("isError"):
            return {"ok": False, "error": output or "Composio tool reported an error."}
        return {
            "ok": True,
            "untrusted_external_content": True,
            "result": output,
        }


def _read_only_allowlist(server):
    allowed = set()
    for tool in server.list_tools():
        name = str(tool.get("name") or "")
        annotations = tool.get("annotations") or {}
        if annotations.get("readOnlyHint") is True or name in _ALLOWED_META_TOOLS:
            allowed.add(name)
    return allowed


def _boot():
    api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
    if not api_key:
        return
    user_id = os.getenv("JARVIS_COMPOSIO_USER_ID", "jarvis-local").strip()
    if not user_id:
        _log("JARVIS_COMPOSIO_USER_ID is empty; integration not started")
        return
    try:
        _session_id, mcp_url = _load_or_create_session(api_key, user_id)
        server = ComposioHTTPMCP("composio", mcp_url, api_key)
        server.start()
        allow = _read_only_allowlist(server)
        if not allow:
            raise RuntimeError(
                "No read-only Composio tools or supported connection tools were exposed."
            )
        server.allow = allow
        added = mcp_client._register_server_tools(server)
        _log(
            f"session ready; {added} read-only/connection tool(s) registered "
            f"from {len(allow)} allowed tools across {len(_toolkits())} configured toolkits"
        )
    except Exception as exc:
        _log(f"startup failed: {type(exc).__name__}: {str(exc)[:260]}")


def start_all_async():
    """Start Composio only when an API key is explicitly configured."""
    if not os.getenv("COMPOSIO_API_KEY", "").strip():
        return
    threading.Thread(target=_boot, name="jarvis-composio-mcp", daemon=True).start()


def register_status_tool():
    """Expose a harmless status check even when Composio is not configured."""
    def status(_arguments):
        configured = bool(os.getenv("COMPOSIO_API_KEY", "").strip())
        return {
            "ok": True,
            "configured": configured,
            "user_id": os.getenv("JARVIS_COMPOSIO_USER_ID", "jarvis-local"),
            "toolkits": _toolkits(),
            "session_file_exists": SESSION_FILE.is_file(),
            "note": (
                "Composio startup is asynchronous; inspect logs/mcp.log for connection status."
                if configured else "Set COMPOSIO_API_KEY in the private .env to enable Composio."
            ),
        }

    registry.register(
        "composio_status",
        "Report whether the optional Composio integration is configured and which app toolkits are selected. This is read-only.",
        {"type": "object", "properties": {}},
        status,
    )
