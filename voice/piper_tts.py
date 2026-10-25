"""Piper TTS backend with a persistent, prewarmed localhost synthesis service."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

from voice.tts import prepare_text

_synth_lock = threading.Lock()
_state_lock = threading.Lock()
_server_lock = threading.Lock()
_synth = None
_lib = None
_runtime_lib = None
_server_process = None
_local_proc = None
_generation = 0


class _AudioChunk(ctypes.Structure):
    _fields_ = [
        ("samples", ctypes.POINTER(ctypes.c_int16)),
        ("num_samples", ctypes.c_size_t),
        ("sample_rate", ctypes.c_uint32),
        ("is_last", ctypes.c_bool),
        ("phonemes", ctypes.c_void_p),
        ("num_phonemes", ctypes.c_size_t),
        ("phoneme_ids", ctypes.c_void_p),
        ("num_phoneme_ids", ctypes.c_size_t),
        ("alignments", ctypes.c_void_p),
        ("num_alignments", ctypes.c_size_t),
    ]


def _settings():
    root = Path(__file__).resolve().parents[1]
    return {
        "library": root / "lib/piper/libpiper.so",
        "model": root / "models/piper/en_GB-alan-medium.onnx",
        "config": root / "models/piper/en_GB-alan-medium.onnx.json",
        "espeak": root / "voice/data/espeak-ng-data",
        "output": root / "cache/piper",
    }


def _load():
    """Load Piper and its ONNX runtime once per persistent server process."""
    global _lib, _synth, _runtime_lib
    if _synth:
        return _lib, _synth
    cfg = _settings()
    for key in ("library", "model", "config"):
        if not cfg[key].is_file():
            raise RuntimeError(f"Piper {key} file not found: {cfg[key]}. Run python setup.py voice.")
    if not cfg["espeak"].is_dir() or not any(cfg["espeak"].iterdir()):
        raise RuntimeError(f"eSpeak NG data directory missing or empty: {cfg['espeak']}. Install/copy eSpeak NG data first.")
    try:
        private_runtime = cfg["library"].parent / "libonnxruntime.so"
        if private_runtime.is_file():
            _runtime_lib = ctypes.CDLL(str(private_runtime), mode=ctypes.RTLD_GLOBAL)
        lib = ctypes.CDLL(str(cfg["library"]))
        lib.piper_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.piper_create.restype = ctypes.c_void_p
        lib.piper_free.argtypes = [ctypes.c_void_p]
        lib.piper_free.restype = None
        lib.piper_synthesize_start.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]
        lib.piper_synthesize_start.restype = ctypes.c_int
        lib.piper_synthesize_next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_AudioChunk)]
        lib.piper_synthesize_next.restype = ctypes.c_int
        synth = lib.piper_create(
            os.fsencode(cfg["model"]), os.fsencode(cfg["config"]), os.fsencode(cfg["espeak"])
        )
    except (OSError, AttributeError) as exc:
        raise RuntimeError(f"Could not load Piper C API from {cfg['library']}: {exc}") from exc
    if not synth:
        raise RuntimeError("Piper failed to initialize the model.")
    _lib, _synth = lib, synth
    return _lib, _synth


def _synthesize_to_wav(text: str) -> Path:
    """Synthesize to a temporary WAV using the already-loaded model."""
    text = prepare_text(text)
    if not text:
        raise RuntimeError("Piper received empty text.")
    cfg = _settings()
    cfg["output"].mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="speech-", suffix=".wav", dir=str(cfg["output"]))
    os.close(fd)
    audio_path = Path(name)
    try:
        # Piper's C API owns one synthesis state, so serialize inference. The
        # server can still synthesize chunk N+1 while mpv plays chunk N.
        with _synth_lock:
            lib, synth = _load()
            rc = lib.piper_synthesize_start(synth, text.encode("utf-8"), None)
            if rc != 0:
                raise RuntimeError(f"Piper synthesis start returned status {rc}")
            audio_chunks, sample_rate = [], 0
            while True:
                chunk = _AudioChunk()
                rc = lib.piper_synthesize_next(synth, ctypes.byref(chunk))
                if rc == 1:
                    break
                if rc != 0:
                    raise RuntimeError(f"Piper synthesis returned status {rc}")
                if chunk.num_samples and chunk.samples:
                    sample_rate = int(chunk.sample_rate)
                    audio_chunks.append(
                        ctypes.string_at(
                            chunk.samples,
                            int(chunk.num_samples) * ctypes.sizeof(ctypes.c_int16),
                        )
                    )
                if chunk.is_last:
                    break
        if not audio_chunks or not sample_rate:
            raise RuntimeError("Piper returned no audio samples.")
        with wave.open(str(audio_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"".join(audio_chunks))
        return audio_path
    except Exception:
        audio_path.unlink(missing_ok=True)
        raise


def _server_url() -> str:
    return f"http://127.0.0.1:{int(os.environ.get('JARVIS_PIPER_SERVER_PORT', '21341'))}"


def _server_healthy(timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(_server_url() + "/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("ok") and payload.get("service") == "jarvis-piper-tts" and payload.get("warmed"))
    except (OSError, ValueError, urllib.error.URLError):
        return False


def warmup() -> bool:
    """Start the local service and wait until Piper's model is loaded."""
    global _server_process
    if _server_healthy():
        return True
    with _server_lock:
        if _server_healthy():
            return True
        root = Path(__file__).resolve().parents[1]
        cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "jarvis"
        cache.mkdir(parents=True, exist_ok=True)
        log_path = cache / "piper_tts_server.log"
        log = log_path.open("a", encoding="utf-8")
        try:
            _server_process = subprocess.Popen(
                [os.sys.executable, "-m", "voice.piper_server"],
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            log.close()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if _server_healthy():
                return True
            if _server_process.poll() is not None:
                break
            time.sleep(0.25)
    detail = ""
    try:
        detail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:])
    except OSError:
        pass
    raise RuntimeError(
        "Piper localhost service failed to warm its model. "
        f"See {log_path}. {detail[-1200:]}"
    )


def _post(path: str, payload: dict, timeout: float):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        _server_url() + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Piper localhost service failed"))
            return result
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Piper localhost HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Piper localhost request failed: {exc.reason}") from exc


def interrupt() -> None:
    global _generation, _local_proc
    with _state_lock:
        _generation += 1
        proc = _local_proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        if _server_healthy():
            _post("/interrupt", {}, timeout=0.7)
    except Exception:
        pass


def speak(text, wait=True, speed=1.0):
    text = str(text or "").strip()
    if not text:
        return False
    warmup()
    result = _post(
        "/speak",
        {"text": text, "speed": float(speed), "wait": bool(wait)},
        timeout=300 if wait else 3,
    )
    return True if wait else result
