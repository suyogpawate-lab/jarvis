#!/usr/bin/env python3
"""Local JARVIS workspace server. Android/Termux compatible; stdlib only."""
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from workspace.manager import WorkspaceManager

HOST = "127.0.0.1"
PORT = int(os.environ.get("JARVIS_WORKSPACE_PORT", "8767"))
TOKEN = secrets.token_urlsafe(24)
ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "web" / "workspace.html"
manager = WorkspaceManager()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def allowed(self, write=False):
        port = self.server.server_address[1]
        if (self.headers.get("Host") or "").lower() not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        peer = self.client_address[0].split("%", 1)[0]
        if peer not in ("127.0.0.1", "::1"):
            return False
        if write:
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                return False
            return secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN)
        return True

    def send(self, status, payload, content_type="application/json"):
        raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if "charset" not in content_type else ""))
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.allowed():
            return self.send(403, '{"error":"forbidden"}')
        path = urlparse(self.path).path
        if path == "/":
            try:
                page = PAGE.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
                return self.send(200, page, "text/html")
            except OSError:
                return self.send(500, "workspace.html missing", "text/plain")
        if path == "/api/snapshot":
            return self.send(200, json.dumps(manager.snapshot()))
        if path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            seq = 0
            try:
                while True:
                    batch = manager.events_after(seq)
                    for event in batch:
                        self.wfile.write(("id: %d\nevent: %s\ndata: %s\n\n" %
                                          (event["id"], event["event"], json.dumps(event["data"]))).encode())
                        seq = event["id"]
                    if not batch:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
        return self.send(404, '{"error":"not found"}')

    def do_POST(self):
        if not self.allowed(write=True):
            return self.send(403, '{"error":"forbidden"}')
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 16384:
                return self.send(413, '{"error":"request too large"}')
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            path = urlparse(self.path).path
            if path == "/api/surfaces/open":
                item = manager.open_surface(data.get("kind"), data.get("title"), data.get("url", ""), data.get("metadata"))
                return self.send(201, json.dumps({"ok": True, "surface": item}))
            if path == "/api/surfaces/close":
                ok = manager.close_surface(data.get("id", ""))
                return self.send(200 if ok else 404, json.dumps({"ok": ok}))
            if path == "/api/surfaces/update":
                item = manager.update_surface(data.get("id", ""), data)
                return self.send(200 if item else 404, json.dumps({"ok": bool(item), "surface": item}))
            if path == "/api/tasks/event":
                item = manager.task_event(data.get("id"), data.get("name"), data.get("status", "active"), data.get("detail", ""))
                return self.send(200, json.dumps({"ok": True, "task": item}))
            if path == "/api/telemetry":
                item = manager.telemetry(data)
                return self.send(200, json.dumps({"ok": True, "telemetry": item}))
            if path == "/api/intent":
                text = str(data.get("text", "")).strip()
                low = text.lower()
                # Deterministic intent shortcuts; complex language should be routed
                # through JARVIS's existing brain and then the typed surface API.
                kinds = (("youtube", "youtube"), ("video", "video"), ("image", "image"),
                         ("website", "web"), ("webpage", "web"), ("browser", "web"),
                         ("terminal", "terminal"), ("tools", "tools"), ("telemetry", "telemetry"),
                         ("screen", "live_screen"), ("live screen", "live_screen"))
                kind = next((k for phrase, k in kinds if phrase in low), None)
                if not kind:
                    return self.send(422, '{"ok":false,"error":"intent needs JARVIS brain classification"}')
                import re
                match = re.search(r"https?://[^\\s]+", text)
                item = manager.open_surface(kind, kind.replace("_", " ").title(), match.group(0).rstrip(".,)") if match else "")
                return self.send(201, json.dumps({"ok": True, "surface": item}))
            return self.send(404, '{"error":"not found"}')
        except OverflowError as exc:
            return self.send(409, json.dumps({"ok": False, "error": str(exc)}))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.send(400, json.dumps({"ok": False, "error": str(exc)}))


if __name__ == "__main__":
    print(f"[JARVIS WORKSPACE] http://{HOST}:{PORT}", flush=True)
    print(f"[JARVIS WORKSPACE] Token: {TOKEN}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
