#!/usr/bin/env python3
"""JARVIS web UI server (localhost only, standard library only).

Started automatically by jarvis_ui.py and jarvis.py via start(). It mirrors the terminal UI:
same state, same themes (read live from jarvis_ui.THEMES), same chat pipeline.
Open the printed URL (default http://127.0.0.1:8765) in the phone's browser.
Env: JARVIS_WEB=0 disables it, JARVIS_WEB_PORT changes the port.
Security: loopback only, Host/Origin checks, and POSTs need the per-run token embedded in the page.
"""
import json, os, re, secrets, threading, time
from workspace.manager import WorkspaceManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HOME, "web", "index.html")
_srv = {"url": None, "ui": None, "token": secrets.token_urlsafe(24), "headless": False}

# ── chat history (shown in the web UI's chat panel; persisted so a page reload keeps it) ──
HIST_FILE = os.path.join(HOME, "data", "web_chat.json")
HIST_MAX = 300
_hist = {"msgs": [], "n": 0, "lock": threading.Lock(), "watch": False}
_workspace = WorkspaceManager()
_workspace_events = os.path.join(HOME, "data", "workspace_events.jsonl")


def _watch_workspace_events():
    """Consume workspace intents in the main JARVIS web process."""
    try:
        position = os.path.getsize(_workspace_events)
    except OSError:
        position = 0
    while True:
        try:
            with open(_workspace_events, encoding="utf-8") as stream:
                stream.seek(position)
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    position = stream.tell()
                    try:
                        record = json.loads(line)
                        data = record.get("data") or {}
                        event = record.get("event")
                        if event == "surface.open":
                            _workspace.open_surface(data.get("kind"), data.get("title"),
                                                     data.get("url", ""), data.get("metadata"))
                        elif event == "surface.command":
                            _workspace.control_surfaces(data.get("action"), data.get("title"))
                        elif event == "task.update":
                            _workspace.task_event(data.get("id"), data.get("name"),
                                                  data.get("status", "active"), data.get("detail", ""))
                        elif event == "presence.update":
                            _workspace.presence(data.get("state"))
                    except (ValueError, TypeError, OverflowError):
                        continue
        except OSError:
            pass
        time.sleep(0.2)


def _hist_load():
    try:
        with open(HIST_FILE, encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, list):
            _hist["msgs"] = [x for x in m if isinstance(x, dict) and x.get("role") in ("user", "assistant")][-HIST_MAX:]
            _hist["n"] = max([x.get("id", 0) for x in _hist["msgs"]] + [0])
    except Exception:
        pass


def _hist_add(role, text):
    text = str(text or "").strip()
    if not text:
        return
    with _hist["lock"]:
        _hist["n"] += 1
        _hist["msgs"].append({"id": _hist["n"], "role": role, "text": text, "t": time.time()})
        del _hist["msgs"][:-HIST_MAX]
        try:
            os.makedirs(os.path.dirname(HIST_FILE), exist_ok=True)
            with open(HIST_FILE, "w", encoding="utf-8") as f:
                json.dump(_hist["msgs"], f, ensure_ascii=False)
        except OSError:
            pass


def _hist_clear():
    with _hist["lock"]:
        _hist["msgs"].clear()
        _hist["n"] += 1
        try:
            os.remove(HIST_FILE)
        except OSError:
            pass


def _watch_replies(ui):
    """Record every new JARVIS reply (typed, voice or notification) into the chat history."""
    last = ui.S.get("reply_t")
    while True:
        time.sleep(0.15)
        rt = ui.S.get("reply_t")
        if rt != last:
            last = rt
            if ui.S.get("reply"):
                _hist_add("assistant", ui.S["reply"])


def _snap(ui):
    S = ui.S
    return {"state": S["state"], "busy": bool(S["busy"] and S.get("thinking")), "reply": S["reply"],
            "reply_t": S["reply_t"], "theme": ui.TH_NAME, "pending": ui.pending_items(), "hn": _hist["n"]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _allowed(self, post=False):
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").lower()
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        if post:
            org = self.headers.get("Origin")
            if org and org not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                return False
            return secrets.compare_digest(self.headers.get("X-Token", ""), _srv["token"])
        return True

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        ui = _srv["ui"]
        if not self._allowed():
            return self._send(403, '{"error":"forbidden"}')
        if self.path.split("?")[0] == "/":
            try:
                html = open(PAGE, encoding="utf-8").read()
            except OSError:
                return self._send(500, "web/index.html is missing", "text/plain")
            html = (html.replace("__TOKEN__", _srv["token"])
                        .replace("__THEMES__", json.dumps(ui.THEMES))
                        .replace("__ORDER__", json.dumps(ui.THEME_ORDER)))
            return self._send(200, html, "text/html")
        if self.path == "/api/history":
            with _hist["lock"]:
                return self._send(200, json.dumps({"msgs": list(_hist["msgs"]), "n": _hist["n"]}))
        if self.path == "/api/workspace/snapshot":
            return self._send(200, json.dumps(_workspace.snapshot()))
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last, beat = None, time.time()
            try:
                while True:
                    if _srv["headless"]:
                        ui.cycle_tick()
                    cur = json.dumps(_snap(ui))
                    if cur != last:
                        self.wfile.write(f"data: {cur}\n\n".encode())
                        last, beat = cur, time.time()
                    elif time.time() - beat > 15:
                        self.wfile.write(b": ping\n\n")
                        beat = time.time()
                    self.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                return
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        ui = _srv["ui"]
        if not self._allowed(post=True):
            return self._send(403, '{"error":"forbidden"}')
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, '{"error":"bad json"}')
        if self.path == "/api/chat":
            text = str(data.get("text", ""))
            res = ui.web_submit(text)
            if res == "ok" and not text.strip().startswith("/"):
                _hist_add("user", text)
            return self._send(200, json.dumps({"result": res}))
        if self.path == "/api/clear":
            _hist_clear()
            return self._send(200, '{"ok":true}')
        if self.path == "/api/workspace/open":
            try:
                item = _workspace.open_surface(data.get("kind"), data.get("title"),
                                                data.get("url", ""), data.get("metadata"))
                return self._send(201, json.dumps({"ok": True, "surface": item}))
            except (ValueError, TypeError, OverflowError) as exc:
                return self._send(400, json.dumps({"ok": False, "error": str(exc)}))
        if self.path == "/api/workspace/control":
            try:
                changed = _workspace.control_surfaces(data.get("action"), data.get("title"))
                return self._send(200, json.dumps({"ok": True, "changed": changed}))
            except ValueError as exc:
                return self._send(400, json.dumps({"ok": False, "error": str(exc)}))
        if self.path == "/api/workspace/close":
            ok = _workspace.close_surface(data.get("id", ""))
            return self._send(200 if ok else 404, json.dumps({"ok": ok}))
        if self.path == "/api/workspace/update":
            try:
                item = _workspace.update_surface(data.get("id", ""), data)
                return self._send(200 if item else 404, json.dumps({"ok": bool(item), "surface": item}))
            except ValueError as exc:
                return self._send(400, json.dumps({"ok": False, "error": str(exc)}))
        if self.path == "/api/theme":
            return self._send(200, json.dumps({"ok": bool(ui.set_theme(str(data.get("name", ""))))}))
        if self.path == "/api/decide":
            act, kind, code = data.get("action"), data.get("kind"), str(data.get("code", ""))
            ok = act in ("approve", "deny") and any(
                i["kind"] == kind and i["code"] == code for i in ui.pending_items(True)
                if kind == "wa" or re.fullmatch(r"[0-9a-f]{4}", code))
            if not ok:
                return self._send(409, '{"result":"not pending"}')
            item = {"kind": kind, "code": code}
            return self._send(200, json.dumps({"result": ui.decide(item, act == "approve")}))
        self._send(404, '{"error":"not found"}')


def start(ui, brain=None):
    """Start the server once. ui = the jarvis_ui module object; brain = jarvis.py module if ui has none."""
    if os.environ.get("JARVIS_WEB", "1") == "0":
        return None
    if _srv["url"]:
        return _srv["url"]
    if brain is not None and getattr(ui, "BRAIN", None) is None:
        ui.BRAIN, _srv["headless"] = brain, True
    _srv["ui"] = ui
    if not _hist["watch"]:
        _hist["watch"] = True
        _hist_load()
        threading.Thread(target=_watch_replies, args=(ui,), daemon=True).start()
    base = int(os.environ.get("JARVIS_WEB_PORT", "8765"))
    for port in range(base, base + 10):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), H)
            break
        except OSError:
            continue
    else:
        return None
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=_watch_workspace_events, daemon=True).start()
    _srv["url"] = f"http://127.0.0.1:{port}"
    ui.WEB_URL = f":{port}"
    return _srv["url"]
