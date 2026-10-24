"""RAM-only receiver for continuous JPEG frames from the Android companion app.

Wire format: each frame is prefixed by a 4-byte unsigned big-endian length.
The Android MediaProjection service sends frames continuously; this is a stream,
not an HTTP screenshot polling loop.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
from typing import Any

STREAM_HOST = "127.0.0.1"
STREAM_PORT = int(os.environ.get("JARVIS_SCREEN_STREAM_PORT", "21340"))
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = int(os.environ.get("JARVIS_SCREEN_CONTROL_PORT", "21341"))
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_CONTROL_TEXT = 2000
MAX_CONTROL_RESPONSE_BYTES = 512 * 1024


class ScreenCastReceiver:
    def __init__(self, host: str = STREAM_HOST, port: int = STREAM_PORT):
        self.host = host
        self.port = port
        self._lock = threading.RLock()
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._latest_jpeg: bytes | None = None
        self._latest_at = 0.0
        self._frames = 0
        self._bytes = 0
        self._clients = 0
        self._last_error = ""

    def start(self) -> "ScreenCastReceiver":
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self
            self._stop.clear()
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(2)
            server.settimeout(1.0)
            self._server = server
            self._thread = threading.Thread(target=self._serve, name="jarvis-screen-cast", daemon=True)
            self._thread.start()
        print(f"[JARVIS SCREEN CAST] Listening on {self.host}:{self.port}", flush=True)
        return self

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            server, self._server = self._server, None
        if server:
            try:
                server.close()
            except OSError:
                pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)

    @staticmethod
    def _read_exact(conn: socket.socket, length: int) -> bytes | None:
        chunks = bytearray()
        while len(chunks) < length:
            try:
                part = conn.recv(length - len(chunks))
            except OSError:
                return None
            if not part:
                return None
            chunks.extend(part)
        return bytes(chunks)

    def _serve(self) -> None:
        while not self._stop.is_set():
            server = self._server
            if server is None:
                break
            try:
                conn, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(10)
                with self._lock:
                    self._clients += 1
                try:
                    while not self._stop.is_set():
                        header = self._read_exact(conn, 4)
                        if header is None:
                            break
                        size = struct.unpack("!I", header)[0]
                        if size < 4 or size > MAX_FRAME_BYTES:
                            raise ValueError(f"invalid frame length: {size}")
                        frame = self._read_exact(conn, size)
                        if frame is None:
                            break
                        if not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"):
                            raise ValueError("frame is not a complete JPEG")
                        with self._lock:
                            self._latest_jpeg = frame
                            self._latest_at = time.time()
                            self._frames += 1
                            self._bytes += size
                except (OSError, ValueError) as exc:
                    with self._lock:
                        self._last_error = str(exc)
                finally:
                    with self._lock:
                        self._clients = max(0, self._clients - 1)

    def latest_frame(self) -> tuple[bytes | None, float]:
        with self._lock:
            return self._latest_jpeg, self._latest_at

    def status(self) -> dict[str, Any]:
        with self._lock:
            age = max(0.0, time.time() - self._latest_at) if self._latest_at else None
            return {
                "ok": True,
                "service": "jarvis-screen-cast",
                "streaming": bool(self._latest_jpeg and age is not None and age < 3.0),
                "frames_received": self._frames,
                "bytes_received": self._bytes,
                "connected_clients": self._clients,
                "last_frame_age_seconds": round(age, 3) if age is not None else None,
                "latest_frame_bytes": len(self._latest_jpeg) if self._latest_jpeg else 0,
                "last_error": self._last_error,
                "storage": "RAM only",
            }

    def control(self, action: dict[str, Any], host: str = CONTROL_HOST, port: int = CONTROL_PORT) -> dict[str, Any]:
        """Send a constrained action to the companion AccessibilityService."""
        if not isinstance(action, dict):
            raise ValueError("action must be a JSON object")
        kind = str(action.get("action", "")).lower().strip()
        allowed = {"tap", "swipe", "type", "back", "home", "recents", "notifications", "snapshot", "click_element"}
        if kind not in allowed:
            raise ValueError("unsupported action; allowed: " + ", ".join(sorted(allowed)))
        clean: dict[str, Any] = {"action": kind, "request_id": str(action.get("request_id", ""))[:80]}
        if kind == "tap":
            clean["x"] = _coordinate(action.get("x"), "x")
            clean["y"] = _coordinate(action.get("y"), "y")
        elif kind == "swipe":
            for field in ("x1", "y1", "x2", "y2"):
                clean[field] = _coordinate(action.get(field), field)
            duration = action.get("duration_ms", 350)
            if isinstance(duration, bool) or not isinstance(duration, (int, float)):
                raise ValueError("duration_ms must be numeric")
            clean["duration_ms"] = int(max(80, min(1500, duration)))
        elif kind == "click_element":
            index = action.get("element_index")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 250:
                raise ValueError("element_index must be an integer from 0 to 249")
            clean["element_index"] = index
        elif kind == "type":
            value = action.get("text")
            if not isinstance(value, str) or not value or len(value) > MAX_CONTROL_TEXT:
                raise ValueError(f"text must contain 1 to {MAX_CONTROL_TEXT} characters")
            clean["text"] = value
        try:
            with socket.create_connection((host, port), timeout=3) as conn:
                conn.settimeout(5)
                conn.sendall((json.dumps(clean, ensure_ascii=False) + "\n").encode("utf-8"))
                response = bytearray()
                while len(response) < MAX_CONTROL_RESPONSE_BYTES:
                    part = conn.recv(min(4096, MAX_CONTROL_RESPONSE_BYTES - len(response)))
                    if not part:
                        break
                    response.extend(part)
                    if b"\n" in part:
                        break
                if len(response) >= MAX_CONTROL_RESPONSE_BYTES and b"\n" not in response:
                    return {"ok": False, "error": "Android screen hierarchy exceeded the response limit"}
            if not response:
                return {"ok": False, "error": "Android control service closed without a response"}
            return json.loads(bytes(response).split(b"\n", 1)[0].decode("utf-8"))
        except OSError as exc:
            return {"ok": False, "error": f"Android control service unavailable: {exc}. Start the companion app and enable its Accessibility Service."}


def _coordinate(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = int(value)
    if not 0 <= result <= 10000:
        raise ValueError(f"{field} must be between 0 and 10000")
    return result


_receiver: ScreenCastReceiver | None = None
_receiver_lock = threading.Lock()


def get_receiver(start: bool = False) -> ScreenCastReceiver:
    global _receiver
    with _receiver_lock:
        if _receiver is None:
            _receiver = ScreenCastReceiver()
        receiver = _receiver
    if start:
        receiver.start()
    return receiver
