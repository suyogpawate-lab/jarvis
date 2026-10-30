"""Shared persistent Phonon inference service.

One service owns the Rust worker and loaded checkpoint for all JARVIS processes.
The service only reports healthy after a real synthesis warmup has produced a valid WAV.
"""
from __future__ import annotations

import base64
import json
import os
import select
import subprocess
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

# Ensure imports work when launched as voice/phonon_server.py.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis_env import load_env

load_env()

from voice.phonon_tts import ROOT, WORKER_BIN, _build_worker, _voice_and_quant, model_dir

HOST = "127.0.0.1"
PORT = 21342
MAX_TEXT_CHARS = 20000
_worker_lock = threading.RLock()
_state_lock = threading.Lock()
_worker = None
_worker_warmed = False
_worker_busy = False
_generation = 0
_worker_read_buffers = {}


def _temp_wav() -> Path:
    prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    directory = prefix / "tmp"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        directory = Path(tempfile.gettempdir())
    fd, name = tempfile.mkstemp(prefix="jarvis-phonon-service-", suffix=".wav", dir=str(directory))
    os.close(fd)
    path = Path(name)
    path.unlink(missing_ok=True)
    return path


def _readline(process, timeout: float) -> str:
    """Read one protocol line without losing lines buffered during PCM streaming."""
    if process.stdout is None:
        raise RuntimeError("Phonon worker stdout is unavailable.")
    buffer = _worker_read_buffers.setdefault(process.pid, bytearray())
    deadline = time.monotonic() + timeout
    while True:
        newline = buffer.find(b"\n")
        if newline >= 0:
            line = bytes(buffer[:newline])
            del buffer[:newline + 1]
            return line.decode("utf-8")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"Phonon worker timed out after {timeout:.0f} seconds.")
        ready, _, _ = select.select([process.stdout], [], [], remaining)
        if not ready:
            raise RuntimeError(f"Phonon worker timed out after {timeout:.0f} seconds.")
        chunk = os.read(process.stdout.fileno(), 4096)
        if not chunk:
            raise RuntimeError("Phonon worker exited before replying.")
        buffer.extend(chunk)


def _exchange(process, text: str, voice: str, output: Path, timeout: float = 180.0) -> None:
    if process.poll() is not None:
        raise RuntimeError("Phonon worker is not running.")
    if process.stdin is None:
        raise RuntimeError("Phonon worker stdin is unavailable.")
    request = {"text": text, "voice": voice, "output": str(output)}
    process.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
    process.stdin.flush()
    response = json.loads(_readline(process, timeout))
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or "Phonon synthesis failed."))


def _stop_worker_locked() -> None:
    global _worker, _worker_warmed, _worker_busy
    with _state_lock:
        process = _worker
        _worker = None
        _worker_warmed = False
        _worker_busy = False
        if process is not None:
            _worker_read_buffers.pop(process.pid, None)
    if process is not None and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except OSError:
                pass


def _ensure_worker_locked() -> subprocess.Popen:
    """Start the worker once, run a real synthesis, and retain it for reuse."""
    global _worker, _worker_warmed
    with _state_lock:
        process = _worker
        warmed = _worker_warmed
    if process is not None and process.poll() is None and warmed:
        return process

    if process is None or process.poll() is not None:
        _stop_worker_locked()
        directory = model_dir()
        voice, quant = _voice_and_quant(directory)
        binary = _build_worker()
        process = subprocess.Popen(
            [str(binary), str(directory), voice, quant],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=False,
            bufsize=0,
            cwd=str(ROOT),
        )
        try:
            ready = json.loads(_readline(process, 900.0))
            if not ready.get("ready"):
                raise RuntimeError(str(ready.get("error") or "Phonon worker did not report ready."))
            with _state_lock:
                _worker = process
                _worker_warmed = False
        except Exception:
            if process.poll() is None:
                process.terminate()
            raise

    directory = model_dir()
    voice, _quant = _voice_and_quant(directory)
    test_wav = _temp_wav()
    try:
        _exchange(process, "JARVIS voice warmup.", voice, test_wav, timeout=180.0)
        if not test_wav.is_file() or test_wav.stat().st_size <= 44:
            raise RuntimeError("Phonon warmup returned no valid WAV audio.")
        with wave.open(str(test_wav), "rb") as audio:
            if audio.getnframes() <= 0 or audio.getframerate() <= 0:
                raise RuntimeError("Phonon warmup WAV contains no audio frames.")
        with _state_lock:
            if _worker is process and process.poll() is None:
                _worker_warmed = True
        print("[JARVIS Phonon] Model initialized; real synthesis warmup passed; worker retained.", flush=True)
        print(f"[JARVIS Phonon] Warmup memory: {_memory_for_pid(process.pid)}", flush=True)
        return process
    except Exception:
        _stop_worker_locked()
        raise
    finally:
        test_wav.unlink(missing_ok=True)


def _memory_for_pid(pid: int) -> dict:
    wanted = {"VmRSS", "VmSwap", "VmHWM", "Threads"}
    result = {}
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key in wanted:
                result[key] = value.strip()
    except OSError:
        result["unavailable"] = True
    return result


def _synthesize_bytes(text: str, voice: str) -> bytes:
    global _worker_busy
    with _worker_lock:
        process = _ensure_worker_locked()
        with _state_lock:
            request_generation = _generation
            _worker_busy = True
        output = _temp_wav()
        try:
            _exchange(process, text, voice, output)
            data = output.read_bytes()
            if len(data) <= 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
                raise RuntimeError("Phonon worker returned an invalid WAV file.")
            with _state_lock:
                if request_generation != _generation:
                    raise RuntimeError("Phonon synthesis was interrupted.")
            return data
        except Exception:
            _stop_worker_locked()
            raise
        finally:
            output.unlink(missing_ok=True)
            with _state_lock:
                if request_generation == _generation:
                    _worker_busy = False


def _recover_worker() -> None:
    try:
        with _worker_lock:
            _ensure_worker_locked()
    except Exception as exc:
        print(f"[JARVIS Phonon] Recovery warmup failed: {type(exc).__name__}: {exc}", flush=True)


def _interrupt() -> None:
    global _generation, _worker, _worker_warmed, _worker_busy
    with _state_lock:
        _generation += 1
        busy = _worker_busy
        process = _worker if busy else None
        if busy:
            _worker = None
            _worker_warmed = False
            _worker_busy = False
    # Do not discard a warmed model just because a new prompt stopped nothing.
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
        # Recovery waits for the cancelled request to release _worker_lock.
        threading.Thread(target=_recover_worker, daemon=True, name="PhononRecovery").start()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            self._reply_json(404, {"ok": False, "error": "not found"})
            return
        with _state_lock:
            process = _worker
            warmed = _worker_warmed
        directory = str(model_dir())
        _voice, quant = _voice_and_quant(Path(directory))
        self._reply_json(200 if process is not None and process.poll() is None and warmed else 503, {
            "ok": bool(process is not None and process.poll() is None and warmed),
            "service": "jarvis-phonon-tts",
            "ready": bool(process is not None and process.poll() is None and warmed),
            "warmup_verified": warmed,
            "model_dir": directory,
            "quant": quant,
            "worker_pid": process.pid if process is not None and process.poll() is None else None,
            "worker_memory": _memory_for_pid(process.pid) if process is not None and process.poll() is None else {},
        })

    def do_POST(self):
        if self.path == "/interrupt":
            _interrupt()
            self._reply_json(200, {"ok": True, "interrupted": True})
            return
        if self.path not in ("/speak", "/stream"):
            self._reply_json(404, {"ok": False, "error": "not found"})
            return
        streaming = self.path == "/stream"
        headers_sent = False
        process = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 24000:
                self._reply_json(413, {"ok": False, "error": "request size out of bounds"})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text = " ".join(str(payload.get("text", "")).split())
            voice = str(payload.get("voice", "default")).strip().lower()
            if not text:
                self._reply_json(400, {"ok": False, "error": "text is required"})
                return
            if len(text) > MAX_TEXT_CHARS:
                self._reply_json(413, {"ok": False, "error": "text is too long"})
                return
            allowed = {"edwin", "toby", "aldric", "trevor", "hugh", "spencer", "bramwell", "default"}
            if voice not in allowed:
                self._reply_json(400, {"ok": False, "error": "unsupported Phonon voice"})
                return
            if not streaming:
                audio = _synthesize_bytes(text, voice)
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(audio)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(audio)
                return

            # Keep the warmed worker and forward each PCM chunk as HTTP arrives.
            global _worker_busy
            with _worker_lock:
                process = _ensure_worker_locked()
                with _state_lock:
                    request_generation = _generation
                    _worker_busy = True
                request = {"text": text, "voice": voice, "output": None, "stream": True}
                if process.stdin is None:
                    raise RuntimeError("Phonon worker stdin is unavailable.")
                process.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
                process.stdin.flush()
                first = json.loads(_readline(process, 180.0))
                if not first.get("stream"):
                    raise RuntimeError(str(first.get("error") or "Phonon worker did not start streaming."))
                sample_rate = int(first.get("sample_rate", 24000))
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("X-Audio-Format", "f32le")
                self.send_header("X-Audio-Channels", "1")
                self.send_header("X-Audio-Sample-Rate", str(sample_rate))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                headers_sent = True

                completed = False
                while True:
                    with _state_lock:
                        if request_generation != _generation:
                            raise RuntimeError("Phonon stream was interrupted.")
                    message = json.loads(_readline(process, 180.0))
                    if "chunk" in message:
                        pcm = base64.b64decode(message["chunk"], validate=True)
                        if pcm:
                            self.wfile.write(f"{len(pcm):X}\r\n".encode("ascii"))
                            self.wfile.write(pcm)
                            self.wfile.write(b"\r\n")
                            self.wfile.flush()
                    elif message.get("done"):
                        completed = True
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                        break
                    elif message.get("ok") is False:
                        raise RuntimeError(str(message.get("error") or "Phonon stream synthesis failed."))
                    else:
                        raise RuntimeError("Unexpected message from Phonon streaming worker.")
                if not completed:
                    raise RuntimeError("Phonon stream ended unexpectedly.")
        except Exception as exc:
            if headers_sent:
                # HTTP headers are already committed; close the stream so the
                # client detects truncation instead of receiving fake audio.
                self.close_connection = True
            else:
                self._reply_json(500, {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            # Only retire this request's worker. Recovery may already have
            # installed a replacement after /interrupt; do not stop that one.
            if streaming and process is not None:
                try:
                    with _worker_lock:
                        with _state_lock:
                            request_worker_is_current = _worker is process
                        if request_worker_is_current:
                            _stop_worker_locked()
                except Exception:
                    pass
        finally:
            if streaming and process is not None and "request_generation" in locals():
                with _state_lock:
                    # Do not clear the busy flag belonging to a newer request
                    # or a replacement worker installed during interruption.
                    if request_generation == _generation and _worker is process:
                        _worker_busy = False

    def log_message(self, *_args):
        return


def main() -> None:
    load_env()
    with _worker_lock:
        _ensure_worker_locked()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"[JARVIS Phonon] Shared service ready on http://{HOST}:{PORT}; model warmed and retained.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
