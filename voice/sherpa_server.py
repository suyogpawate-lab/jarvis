"""Persistent localhost Sherpa Piper TTS service with sentence look-ahead.

The process owns the model cache so a model is not reloaded for each utterance.
It warms the selected voice and synthesizes sentence N+1 while mpv plays N.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from voice.sherpa_tts import _engine, _paths
from voice.text_chunking import chunk_text

HOST = "127.0.0.1"
PORT = int(os.environ.get("JARVIS_TTS_SERVER_PORT", "21342"))
VOICE_RE = re.compile(r"(?<=[.!?])\s+")
ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "no.", "fig.", "approx.", "inc.", "ltd.", "co.", "u.s.", "u.k.", "a.m.", "p.m."}
_play_lock = threading.Lock()


def sentences(text: str) -> list[str]:
    """Group long replies near 15 words, splitting only at .?! sentence ends."""
    return chunk_text(text, target_words=15, threshold_words=20)


def synthesize(voice: str, text: str) -> Path:
    import soundfile as sf
    engine = _engine(voice)  # cached by sherpa_tts for this server's lifetime
    audio = engine.generate(text, sid=0, speed=1.0)
    samples = getattr(audio, "samples", None)
    if samples is None or len(samples) == 0:
        raise RuntimeError("Sherpa returned no audio samples.")
    output_dir = _paths(voice)["output"]
    output_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="sentence-", suffix=".wav", dir=str(output_dir))
    os.close(fd)
    path = Path(name)
    sf.write(str(path), samples, audio.sample_rate)
    return path


def speak_pipeline(voice: str, text: str) -> None:
    chunks = sentences(text)
    if not chunks:
        return
    if not shutil.which("mpv"):
        raise RuntimeError("mpv is not installed or not on PATH.")
    # One playback at a time; prepare the next sentence concurrently.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="sherpa-lookahead") as pool:
        future = pool.submit(synthesize, voice, chunks[0])
        for index, chunk in enumerate(chunks):
            current = future.result()
            next_future = pool.submit(synthesize, voice, chunks[index + 1]) if index + 1 < len(chunks) else None
            try:
                with _play_lock:
                    result = subprocess.run(
                        ["mpv", "--no-video", "--no-terminal", "--really-quiet", "--", str(current)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, check=False,
                    )
                if result.returncode:
                    raise RuntimeError(f"mpv exited with status {result.returncode}")
            finally:
                current.unlink(missing_ok=True)
            if next_future is not None:
                future = next_future


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/health":
            self._reply(404, {"ok": False, "error": "not found"})
            return
        self._reply(200, {"ok": True, "service": "jarvis-sherpa-tts", "voices": ["alan", "bryce"], "model_cache": "persistent"})

    def do_POST(self):
        if self.path != "/speak":
            self._reply(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 24000:
                self._reply(413, {"ok": False, "error": "request size out of bounds"})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            voice = str(payload.get("voice", "alan")).strip().lower()
            text = str(payload.get("text", "")).strip()
            if voice not in ("alan", "bryce") or not text:
                self._reply(400, {"ok": False, "error": "voice must be alan/bryce and text is required"})
                return
            speak_pipeline(voice, text)
            self._reply(200, {"ok": True, "voice": voice})
        except Exception as exc:
            self._reply(500, {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:220]}"})

    def log_message(self, *_args):
        return


def main() -> None:
    selected = os.environ.get("JARVIS_SHERPA_VOICE", "alan").strip().lower()
    if selected not in ("alan", "bryce"):
        selected = "alan"
    print(f"[SHERPA TTS SERVER] Warming {selected} model...", flush=True)
    _engine(selected)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"[SHERPA TTS SERVER] Ready on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
