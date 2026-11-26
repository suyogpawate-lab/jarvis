#!/usr/bin/env python3

import json
import sys
import time
import traceback
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import Jarvis
from automation.command_dispatcher import CommandDispatcher
from core.discussion import DiscussionCoordinator
from memory import MemoryManager
from screen_cast.receiver import get_receiver
from screen_cast.perception import analyze_latest_screen, handle_screen_request, get_screen_snapshot, is_screen_context_request
from automation.owner_contact import OwnerContactManager


import os
from jarvis_env import load_env
from intelligence.groq_reasoner import ask_screen_with_groq, ScreenReasoningError
load_env()
TOKEN = os.environ.get("JARVIS_HTTP_TOKEN", "")

HOST = "127.0.0.1"
PORT = 21339



print("[JARVIS HTTP] Initializing JARVIS...", flush=True)

jarvis = Jarvis()
discussion = DiscussionCoordinator()
memory = MemoryManager()

dispatcher = CommandDispatcher(
    jarvis,
    discussion,
    memory,
)

# Continuous JPEG stream receiver. Frames stay in RAM; Android's companion
# app owns MediaProjection consent and sends a framed TCP stream to port 21340.
owner_contact = OwnerContactManager()
screen_receiver = get_receiver()
try:
    screen_receiver.start()
except OSError as exc:
    print(f"[JARVIS SCREEN CAST] Receiver not started: {exc}", flush=True)

# Screen hierarchy is fetched only on explicit requests. The bridge does not
# cache screen JSON/XML; each response is discarded after it is sent.


print(f"[JARVIS HTTP] Ready on http://{HOST}:{PORT}", flush=True)


class JarvisHandler(BaseHTTPRequestHandler):

    def _send_json(self, status, payload):
        data = json.dumps(
            payload,
            ensure_ascii=False
        ).encode("utf-8")

        try:
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8"
            )
            self.send_header(
                "Content-Length",
                str(len(data))
            )
            self.send_header(
                "Cache-Control",
                "no-store"
            )
            self.send_header(
                "Access-Control-Allow-Origin",
                "*"
            )
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # A client may disconnect during headers or body transmission.
            # Do not log response content or attempt a second response.
            return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Token"
        )
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS"
        )
        self.end_headers()

    def _authorized(self):
        # This server binds exclusively to 127.0.0.1. No separate secret is needed
        # for same-device calls; reject non-loopback peers if the bind ever changes.
        peer = self.client_address[0].split("%", 1)[0]
        return peer in ("127.0.0.1", "::1")

    def do_GET(self):

        if self.path == "/health":
            self._send_json(200, {
                "ok": True,
                "service": "JARVIS",
                "status": "online",
                "screen_stream_port": screen_receiver.port,
                "screen_control_port": int(os.environ.get("JARVIS_SCREEN_CONTROL_PORT", "21341")),
                "auth": "loopback-only"
            })
            return

        if self.path == "/screen/diagnostics":
            # Never return screen text or pixels from diagnostics.
            result = screen_receiver.control({"action": "snapshot"})
            self._send_json(200, {
                "ok": bool(result.get("ok") and result.get("type") == "screen_accessibility"),
                "service": "jarvis-screen-diagnostics",
                "stream": screen_receiver.status(),
                "accessibility": {
                    "available": bool(result.get("ok") and result.get("type") == "screen_accessibility"),
                    "response_type": result.get("type"),
                    "error": result.get("error")
                },
                "storage": "RAM only; snapshot discarded"
            })
            return

        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return
        if self.path == "/owner/status":
            self._send_json(200, owner_contact.status())
            return
        if self.path == "/screen/stream/status":
            self._send_json(200, screen_receiver.status())
            return

        if self.path == "/screen/stream/frame":
            frame, timestamp = screen_receiver.latest_frame()
            if not frame:
                self._send_json(404, {"ok": False, "error": "no live frame; start the Android screen-cast companion"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(frame)
            return

        if self.path == "/screen":
            snapshot, error = get_screen_snapshot()
            if error:
                self._send_json(503, {"ok": False, "error": error})
            else:
                self._send_json(200, snapshot)
            return

        self._send_json(404, {
            "ok": False,
            "error": "not found"
        })

    def do_POST(self):
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        if self.path not in ("/chat", "/screen", "/control", "/screen/analyze", "/owner/call", "/owner/wakeup", "/owner/wakeup/cancel"):
            self._send_json(404, {
                "ok": False,
                "error": "not found"
            })
            return

        try:
            length = int(
                self.headers.get("Content-Length", "0")
            )

            raw = self.rfile.read(length)

            body = json.loads(
                raw.decode("utf-8")
            )

            # ======================================================
            # LOCAL OWNER CALLING (no SIM or remote telephony provider)
            # ======================================================
            if self.path == "/owner/call":
                result = owner_contact.request_call(
                    reason=body.get("reason", "assistant_update"),
                    message=body.get("message", ""),
                    priority=body.get("priority", "normal"),
                    source=body.get("source", "jarvis"),
                    event_id=body.get("event_id"),
                    dedupe_seconds=body.get("dedupe_seconds", 600),
                )
                self._send_json(200, result)
                return

            if self.path == "/owner/wakeup":
                result = owner_contact.schedule_wakeup(
                    body.get("at_epoch"),
                    message=body.get("message", "JARVIS wake-up call"),
                    event_id=body.get("event_id"),
                )
                self._send_json(200, result)
                return

            if self.path == "/owner/wakeup/cancel":
                result = owner_contact.cancel_wakeup(body.get("event_id", ""))
                self._send_json(200, result)
                return

            # ======================================================
            # LIVE STREAM PERCEPTION AND ANDROID CONTROL
            # ======================================================

            if self.path == "/control":
                result = screen_receiver.control(body)
                self._send_json(200 if result.get("ok") else 503, result)
                return

            if self.path == "/screen/analyze":
                answer = handle_screen_request(
                    str(body.get("prompt", "Describe the current screen.")),
                    ask=ask_screen_with_groq,
                    receiver=screen_receiver,
                )
                self._send_json(200, {"ok": True, "response": answer, "perception": "accessibility_json", "stream": screen_receiver.status()})
                return

            if self.path == "/chat":
                command_text = str(body.get("command", "")).strip()
                if is_screen_context_request(command_text):
                    answer = handle_screen_request(
                        command_text,
                        ask=ask_screen_with_groq,
                        receiver=screen_receiver,
                    )
                    self._send_json(200, {
                        "ok": True,
                        "response": answer,
                        "perception": "accessibility_json",
                        "stream": screen_receiver.status(),
                    })
                    return
                # Explicit screen commands use a narrow grammar rather than
                # allowing arbitrary model output to become touch input.
                import re
                match = re.fullmatch(r"screen\s+tap\s+(\d+)\s+(\d+)", command_text, re.I)
                if match:
                    result = screen_receiver.control({"action": "tap", "x": int(match.group(1)), "y": int(match.group(2))})
                    self._send_json(200 if result.get("ok") else 503, result)
                    return
                match = re.fullmatch(r"screen\s+swipe\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", command_text, re.I)
                if match:
                    coords = [int(match.group(i)) for i in range(1, 5)]
                    result = screen_receiver.control({"action": "swipe", "x1": coords[0], "y1": coords[1], "x2": coords[2], "y2": coords[3]})
                    self._send_json(200 if result.get("ok") else 503, result)
                    return
                match = re.fullmatch(r"screen\s+type\s+(.+)", command_text, re.I | re.S)
                if match:
                    result = screen_receiver.control({"action": "type", "text": match.group(1)})
                    self._send_json(200 if result.get("ok") else 503, result)
                    return
                match = re.fullmatch(r"screen\s+(back|home|recents|notifications)", command_text, re.I)
                if match:
                    result = screen_receiver.control({"action": match.group(1).lower()})
                    self._send_json(200 if result.get("ok") else 503, result)
                    return

            # Legacy XML ingestion is accepted for compatibility, but the
            # payload is discarded immediately and never cached or logged.
            screen_value = body.get("screen_xml")
            if (
                body.get("type") == "screen_layout"
                or screen_value is not None
                or isinstance(body.get("command"), list)
            ):
                if screen_value is None:
                    screen_value = body.get("command")
                if screen_value is None or (isinstance(screen_value, str) and not screen_value.strip()):
                    self._send_json(400, {"ok": False, "error": "empty screen layout"})
                    return
                self._send_json(200, {
                    "ok": True,
                    "type": "screen_layout",
                    "stored": False,
                    "storage": "RAM only; request payload discarded"
                })
                return

            # ======================================================
            # NORMAL JARVIS CHAT
            # ======================================================

            command = str(
                body.get("command", "")
            ).strip()

            if not command:
                self._send_json(400, {
                    "ok": False,
                    "error": "missing command"
                })
                return

            print("[JARVIS HTTP] Processing chat request.", flush=True)

            result = dispatcher.dispatch(command)

            if result is None:
                result = ""

            result = str(result).strip()

            print("[JARVIS HTTP] Chat response ready.", flush=True)

            self._send_json(200, {
                "ok": True,
                "response": result
            })

        except Exception as exc:

            # Never log request bodies, screen text, credentials, or raw provider
            # response bodies. ScreenReasoningError exposes only a safe category.
            error_code = exc.code if isinstance(exc, ScreenReasoningError) else "internal_error"
            print(
                f"[JARVIS HTTP] Request failed ({type(exc).__name__}; code={error_code}).",
                file=sys.stderr,
                flush=True
            )
            try:
                self._send_json(502 if isinstance(exc, ScreenReasoningError) else 500, {
                    "ok": False,
                    "error_code": error_code,
                    "error": "screen reasoning unavailable" if isinstance(exc, ScreenReasoningError) else "request failed; sensitive request contents were not logged"
                })
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, fmt, *args):
        print(
            f"[JARVIS HTTP] "
            f"{self.address_string()} - "
            f"{fmt % args}",
            flush=True
        )


if __name__ == "__main__":

    server = ThreadingHTTPServer(
        (HOST, PORT),
        JarvisHandler
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print(
            "\n[JARVIS HTTP] Stopping...",
            flush=True
        )

    finally:
        server.server_close()
