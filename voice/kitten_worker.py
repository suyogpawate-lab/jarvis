"""Bundled persistent KittenTTS Pico ONNX worker for JARVIS.

The worker owns one model instance for its lifetime and communicates with the
JARVIS client over a loopback-only newline-delimited JSON socket.
"""
from __future__ import annotations

import json
import os
import socketserver
import time
import traceback
import uuid
import wave
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("JARVIS_KITTEN_PORT", "18765"))
MODEL_ID = os.environ.get("JARVIS_KITTEN_MODEL", "KittenML/kitten-tts-2-pico")
OUTPUT = Path(__file__).resolve().parents[1] / "cache" / "kitten_tts" / "worker"
OUTPUT.mkdir(parents=True, exist_ok=True)

# Keep Hugging Face's normal cache unless the user explicitly configured one.
cache_home = os.environ.get("JARVIS_KITTEN_HOME", "").strip()
if cache_home:
    Path(cache_home).expanduser().mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(Path(cache_home).expanduser())

print(f"[Kitten] Loading {MODEL_ID} with ONNX backend...", flush=True)
from kittenml import KittenTTS

load_started = time.perf_counter()
model = KittenTTS(MODEL_ID, backend="onnx")
load_seconds = time.perf_counter() - load_started
print(f"[Kitten] Model loaded in {load_seconds:.3f}s", flush=True)

print("[Kitten] Warming up ONNX inference...", flush=True)
warmup_path = OUTPUT / f".warmup-{uuid.uuid4().hex}.wav"
warmup_started = time.perf_counter()
model.generate_to_file(
    "Ready.",
    str(warmup_path),
    voice="otis",
    language="en",
    speed=0.88,
)
warmup_seconds = time.perf_counter() - warmup_started
warmup_path.unlink(missing_ok=True)
print(f"[Kitten] Warm-up completed in {warmup_seconds:.3f}s", flush=True)

_last_output: Path | None = None


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        global _last_output
        try:
            raw = self.rfile.readline(1_000_001)
            if not raw or len(raw) > 1_000_000:
                return
            request = json.loads(raw.decode("utf-8"))

            if request.get("action") == "ping":
                self.reply({
                    "ok": True,
                    "status": "ready",
                    "model": MODEL_ID,
                    "load_seconds": load_seconds,
                    "warmup_seconds": warmup_seconds,
                })
                return

            if request.get("action") != "generate":
                self.reply({"ok": False, "error": "Unknown action"})
                return

            text = str(request.get("text") or "").strip()
            if not text:
                self.reply({"ok": False, "error": "Text cannot be empty"})
                return
            if len(text) > 20_000:
                self.reply({"ok": False, "error": "Text is too long"})

                return

            voice = str(request.get("voice") or "otis").strip()
            language = str(request.get("language") or "en").strip().lower()
            speed = float(request.get("speed", 0.88))
            if not 0.5 <= speed <= 2.0:
                self.reply({"ok": False, "error": "Speed must be between 0.5 and 2.0"})
                return

            output = OUTPUT / f"speech-{uuid.uuid4().hex}.wav"
            started = time.perf_counter()
            model.generate_to_file(
                text,
                str(output),
                voice=voice,
                language=language,
                speed=speed,
            )
            generation_seconds = time.perf_counter() - started

            with wave.open(str(output), "rb") as wav:
                audio_seconds = (
                    wav.getnframes() / wav.getframerate()
                    if wav.getframerate() else 0.0
                )

            previous = _last_output
            _last_output = output
            if previous and previous != output:
                previous.unlink(missing_ok=True)

            self.reply({
                "ok": True,
                "path": str(output),
                "generation_seconds": generation_seconds,
                "audio_seconds": audio_seconds,
                "rtf": generation_seconds / audio_seconds if audio_seconds else 0.0,
            })
            print(
                f"[Kitten] Generated {output.name}: {generation_seconds:.3f}s, "
                f"audio {audio_seconds:.2f}s, voice={voice}/{language}",
                flush=True,
            )
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            print(f"[Kitten ERROR] {detail}\n{traceback.format_exc()}", flush=True)
            self.reply({"ok": False, "error": detail})

    def reply(self, data):
        self.wfile.write((json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()


class Server(socketserver.TCPServer):
    allow_reuse_address = True


print(f"[Kitten] READY at {HOST}:{PORT}", flush=True)
with Server((HOST, PORT), Handler) as server:
    server.serve_forever()
