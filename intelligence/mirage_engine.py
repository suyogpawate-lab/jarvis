"""Persistent local Cactus Mirage vision worker for JARVIS screen perception."""
from __future__ import annotations

import atexit
import io
import json
import os
import struct
import subprocess
import threading
import time
from pathlib import Path


class MirageEngine:
    def __init__(self):
        root = Path(__file__).resolve().parents[1]
        cactus = Path(os.getenv(
            "JARVIS_MIRAGE_DIR",
            Path.home() / "jarvis-microvision" / "cactus-runtime"
        ))
        self.worker = Path(os.getenv(
            "JARVIS_MIRAGE_WORKER", cactus / "mirage_worker"
        ))
        self.model = Path(os.getenv(
            "JARVIS_MIRAGE_MODEL", cactus / "mirage.cact"
        ))
        self._process = None
        self._lock = threading.Lock()
        self.last_error = None

    def status(self):
        return {
            "model": "Cactus Mirage",
            "worker_exists": self.worker.is_file(),
            "model_exists": self.model.is_file(),
            "loaded": self._process is not None and self._process.poll() is None,
            "last_error": self.last_error,
        }

    def _start(self):
        if self._process is not None and self._process.poll() is None:
            return

        if not self.worker.is_file() or not self.model.is_file():
            raise RuntimeError("Mirage worker or mirage.cact model is missing.")

        self._process = subprocess.Popen(
            [str(self.worker), str(self.model)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        line = self._process.stdout.readline(4096)
        try:
            ready = json.loads(line)
        except Exception as exc:
            self._process.kill()
            self._process = None
            raise RuntimeError("Mirage worker did not send a valid startup handshake.") from exc

        if not ready.get("ready"):
            self._process.kill()
            self._process = None
            raise RuntimeError("Mirage worker did not become ready.")

    def describe_bytes(self, image_bytes: bytes):
        started = time.monotonic()
        try:
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                raise ValueError("No screen frame supplied.")

            from PIL import Image

            with Image.open(io.BytesIO(image_bytes)) as image:
                image = image.convert("RGB")
                image.thumbnail((1024, 1024))
                width, height = image.size
                rgb = image.tobytes()

            with self._lock:
                self._start()
                proc = self._process
                proc.stdin.write(struct.pack("!III", width, height, len(rgb)))
                proc.stdin.write(rgb)
                proc.stdin.flush()

                line = proc.stdout.readline(262144)
                if not line:
                    raise RuntimeError("Mirage worker stopped during inference.")

            result = json.loads(line)
            if not isinstance(result, dict):
                raise RuntimeError("Mirage returned an invalid response.")

            if result.get("ok") is False:
                raise RuntimeError(str(result.get("error", "Mirage inference failed")))

            result["ok"] = True
            result["model"] = "Cactus-Mirage"
            result["latency_ms"] = round(
                (time.monotonic() - started) * 1000, 1
            )
            self.last_error = None
            return result

        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "error": self.last_error}

    def close(self):
        with self._lock:
            if self._process is not None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=2)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None


_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def get_mirage_engine():
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = MirageEngine()
            atexit.register(_ENGINE.close)
        return _ENGINE
