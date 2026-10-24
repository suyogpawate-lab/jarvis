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
from screen_cast.perception import analyze_latest_screen, get_screen_snapshot


import os, hmac
from jarvis_env import load_env
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
            "Access-Control-Allow-Origin",
            "*"
        )
        self.end_headers()

        self.wfile.write(data)

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
        if not TOKEN:
            return False
        return hmac.compare_digest(self.headers.get("X-Token", ""), TOKEN)

    def do_GET(self):

        if self.path == "/health":
            self._send_json(200, {
                "ok": True,
                "service": "JARVIS",
                "status": "online"
            })
            return

        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
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

        if self.path not in ("/chat", "/screen", "/control", "/screen/analyze"):
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
            # LIVE STREAM PERCEPTION AND ANDROID CONTROL
            # ======================================================

            if self.path == "/control":
                result = screen_receiver.control(body)
                self._send_json(200 if result.get("ok") else 503, result)
                return

            if self.path == "/screen/analyze":
                answer = analyze_latest_screen(str(body.get("prompt", "Describe the current screen.")))
                self._send_json(200, {"ok": True, "response": answer, "stream": screen_receiver.status()})
                return

            if self.path == "/chat":
                command_text = str(body.get("command", "")).strip()
                lower = command_text.lower()
                if lower in ("what is on my screen", "what's on my screen", "describe my screen", "look at my screen", "analyze my screen"):
                    answer = analyze_latest_screen(command_text)
                    self._send_json(200, {"ok": True, "response": answer})
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

            # ======================================================
            # EXISTING SCREEN HIERARCHY INGESTION (kept compatible)
            # ======================================================

            screen_value = body.get("screen_xml")

            if (
                body.get("type") == "screen_layout"
                or screen_value is not None
                or isinstance(body.get("command"), list)
            ):

                if screen_value is None:
                    screen_value = body.get("command")

                screen_xml = normalize_screen_xml(
                    screen_value
                )

                if not screen_xml:
                    self._send_json(400, {
                        "ok": False,
                        "error": "empty screen layout"
                    })
                    return

                # Store ONLY in RAM.
                store_screen(screen_xml)

                print(
                    "[JARVIS SCREEN] Received "
                    f"{len(screen_xml)} chars",
                    flush=True
                )

                self._send_json(200, {
                    "ok": True,
                    "type": "screen_layout",
                    "stored": True,
                    "chars": len(screen_xml),
                    "timestamp": time.time()
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

            print(
                f"[JARVIS HTTP] → {command}",
                flush=True
            )

            result = dispatcher.dispatch(command)

            if result is None:
                result = ""

            result = str(result).strip()

            print(
                f"[JARVIS HTTP] ← {result[:200]}",
                flush=True
            )

            self._send_json(200, {
                "ok": True,
                "response": result
            })

        except Exception as exc:

            print(
                f"[JARVIS HTTP] ERROR: {exc}",
                file=sys.stderr,
                flush=True
            )

            traceback.print_exc()

            self._send_json(500, {
                "ok": False,
                "error": str(exc)
            })

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
