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

# ------------------------------------------------------------------
# LIVE SCREEN STATE
# Kept entirely in RAM. Nothing is written to disk.
# ------------------------------------------------------------------

_screen_lock = threading.Lock()

latest_screen_xml = None
latest_screen_time = 0.0


def normalize_screen_xml(value):
    """
    Automate's Node-set may arrive as a list containing XML strings.
    Normalize it into one XML string without touching disk.
    """

    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (list, tuple)):
        parts = []

        for item in value:
            normalized = normalize_screen_xml(item)

            if normalized:
                parts.append(normalized)

        return "\n".join(parts).strip()

    return str(value).strip()


def store_screen(xml):
    global latest_screen_xml
    global latest_screen_time

    with _screen_lock:
        latest_screen_xml = xml
        latest_screen_time = time.time()


def get_screen():
    with _screen_lock:
        return latest_screen_xml, latest_screen_time


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

        # ----------------------------------------------------------
        # Return the latest screen hierarchy currently held in RAM.
        # ----------------------------------------------------------

        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return
        if self.path == "/screen":
            xml, timestamp = get_screen()

            if not xml:
                self._send_json(404, {
                    "ok": False,
                    "error": "no screen data available"
                })
                return

            self._send_json(200, {
                "ok": True,
                "type": "screen_layout",
                "timestamp": timestamp,
                "screen_xml": xml
            })
            return

        self._send_json(404, {
            "ok": False,
            "error": "not found"
        })

    def do_POST(self):
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        if self.path not in ("/chat", "/screen"):
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
            # SCREEN PERCEPTION
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
