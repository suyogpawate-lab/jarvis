"""Persistent localhost Piper service with model warmup and synthesis look-ahead."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from voice.piper_tts import _load, _synthesize_to_wav, _settings
from voice.text_chunking import chunk_text

HOST = "127.0.0.1"
PORT = int(os.environ.get("JARVIS_PIPER_SERVER_PORT", "21341"))
_state_lock = threading.Lock()
_pipeline_lock = threading.Lock()
_generation = 0
_active_process = None


def _generation_value():
    with _state_lock:
        return _generation


def interrupt_pipeline():
    global _generation, _active_process
    with _state_lock:
        _generation += 1
        proc = _active_process
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


def _remove_future_audio(future):
    try:
        path = future.result()
        path.unlink(missing_ok=True)
    except Exception:
        pass


def speak_pipeline(text: str, speed: float = 1.0) -> None:
    global _active_process
    chunks = chunk_text(text, target_words=15, threshold_words=20)
    if not chunks:
        return
    if not shutil.which("mpv"):
        raise RuntimeError("mpv is not installed or not on PATH.")

    with _pipeline_lock:
        token = _generation_value()
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="piper-lookahead") as pool:
            future = pool.submit(_synthesize_to_wav, chunks[0])
            for index, chunk in enumerate(chunks):
                audio_path = future.result()
                if token != _generation_value():
                    audio_path.unlink(missing_ok=True)
                    return
                next_future = (
                    pool.submit(_synthesize_to_wav, chunks[index + 1])
                    if index + 1 < len(chunks)
                    else None
                )
                command = ["mpv", "--no-video", "--no-terminal", "--really-quiet"]
                if speed and float(speed) > 0 and float(speed) != 1.0:
                    command.append(f"--speed={float(speed):.3f}")
                command.extend(["--", str(audio_path)])
                proc = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                with _state_lock:
                    if token != _generation:
                        proc.terminate()
                    _active_process = proc
                try:
                    while proc.poll() is None:
                        if token != _generation_value():
                            try:
                                proc.terminate()
                            except OSError:
                                pass
                            break
                        time.sleep(0.05)
                    code = proc.wait()
                    if token == _generation_value() and code != 0:
                        raise RuntimeError(f"mpv exited with status {code}")
                finally:
                    audio_path.unlink(missing_ok=True)
                    with _state_lock:
                        if _active_process is proc:
                            _active_process = None

                if token != _generation_value():
                    if next_future is not None:
                        next_future.add_done_callback(_remove_future_audio)
                    return
                if next_future is not None:
                    future = next_future


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            self._reply(404, {"ok": False, "error": "not found"})
            return
        self._reply(200, {
            "ok": True,
            "service": "jarvis-piper-tts",
            "warmed": True,
            "model": str(_settings()["model"]),
            "lookahead": True,
        })

    def do_POST(self):
        if self.path == "/interrupt":
            interrupt_pipeline()
            self._reply(200, {"ok": True, "interrupted": True})
            return
        if self.path != "/speak":
            self._reply(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 24000:
                self._reply(413, {"ok": False, "error": "request size out of bounds"})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text = str(payload.get("text", "")).strip()
            speed = float(payload.get("speed", 1.0))
            wait = bool(payload.get("wait", True))
            if not text:
                self._reply(400, {"ok": False, "error": "text is required"})
                return
            if not 0.5 <= speed <= 2.0:
                self._reply(400, {"ok": False, "error": "speed must be between 0.5 and 2.0"})
                return
            if wait:
                speak_pipeline(text, speed)
                self._reply(200, {"ok": True, "service": "jarvis-piper-tts"})
            else:
                threading.Thread(
                    target=self._background_speak,
                    args=(text, speed),
                    daemon=True,
                    name="PiperAsyncSpeech",
                ).start()
                self._reply(202, {"ok": True, "accepted": True})
        except Exception as exc:
            self._reply(500, {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:240]}"})

    @staticmethod
    def _background_speak(text, speed):
        try:
            speak_pipeline(text, speed)
        except Exception as exc:
            print(f"[PIPER TTS SERVER] {type(exc).__name__}: {exc}", flush=True)

    def log_message(self, *_args):
        return


def main() -> None:
    # Force all native library/model errors to surface before /health is ready.
    print("[PIPER TTS SERVER] Warming Piper model...", flush=True)
    _load()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"[PIPER TTS SERVER] Ready on http://{HOST}:{PORT}; model cached; look-ahead enabled.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
