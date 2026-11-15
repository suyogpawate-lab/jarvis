"""Persistent FP16 Kokoro worker client used by JARVIS TTSManager."""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "kokoro82m"
MODEL = MODEL_DIR / "kokoro-v1.0.fp16.onnx"
VOICES = MODEL_DIR / "voices-v1.0.bin"
WORKER = ROOT / "scripts" / "kokoro_worker.py"
_LOCK = threading.RLock()
_PROCESS = None
_READY = None
_LOG = None


def _readline(stream, timeout: float) -> str:
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        raise TimeoutError(f"Kokoro worker did not respond within {timeout:.0f}s")
    line = stream.readline()
    if not line:
        raise RuntimeError("Kokoro worker exited unexpectedly; inspect ~/.cache/jarvis/kokoro_worker.log")
    return line


def _start_worker() -> dict:
    global _PROCESS, _READY, _LOG
    if _PROCESS is not None and _PROCESS.poll() is None and _READY:
        return _READY
    if not MODEL.is_file() or not VOICES.is_file():
        raise RuntimeError("Kokoro FP16 assets missing; run: bash scripts/install_kokoro82m_termux.sh")
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "jarvis"
    cache.mkdir(parents=True, exist_ok=True)
    _LOG = (cache / "kokoro_worker.log").open("a", encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("OMP_NUM_THREADS", os.environ.get("JARVIS_KOKORO_THREADS", "2"))
    _PROCESS = subprocess.Popen(
        [sys.executable, str(WORKER), str(MODEL), str(VOICES)],
        cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=_LOG, text=True, bufsize=1, env=env, start_new_session=True,
    )
    try:
        ready = json.loads(_readline(_PROCESS.stdout, 300.0))
        if not ready.get("ready") or ready.get("voices_loaded", 0) < 54:
            raise RuntimeError(f"Kokoro worker failed startup validation: {ready}")
        _READY = ready
        return ready
    except Exception:
        try:
            _PROCESS.terminate()
            _PROCESS.wait(timeout=2)
        except Exception:
            pass
        _PROCESS = _READY = None
        raise


def warmup() -> bool:
    ready = _start_worker()
    print(
        "[TTS] Kokoro-82M FP16 preloaded in persistent CPU worker; "
        f"{ready['voices_loaded']} voices resident; model load "
        f"{ready.get('model_load_seconds')}s; real inference warmup complete.",
        flush=True,
    )
    return True


def synth(text: str, voice: str | None = None, speed: float = 1.0) -> Path:
    text = " ".join(str(text or "").split())
    if not text:
        raise RuntimeError("Kokoro received empty text.")
    selected = (voice or os.environ.get("JARVIS_KOKORO_VOICE", "jarvis_whisper")).strip()
    speed = max(0.5, min(2.0, float(speed)))
    with _LOCK:
        _start_worker()
        out_dir = Path(tempfile.gettempdir()) / "jarvis-kokoro"
        out_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="speech-", suffix=".wav", dir=str(out_dir))
        os.close(fd)
        output = Path(name)
        output.unlink(missing_ok=True)
        try:
            _PROCESS.stdin.write(json.dumps({
                "text": text, "voice": selected, "speed": speed, "output": str(output)
            }, ensure_ascii=False) + "\n")
            _PROCESS.stdin.flush()
            result = json.loads(_readline(_PROCESS.stdout, 240.0))
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Kokoro synthesis failed"))
            if not output.is_file() or output.stat().st_size <= 44:
                raise RuntimeError("Kokoro reported success but produced no WAV.")
            return output
        except Exception:
            output.unlink(missing_ok=True)
            raise


def interrupt() -> None:
    # Leave the resident inference session loaded; TTSManager stops playback.
    return None


def status() -> dict:
    with _LOCK:
        alive = _PROCESS is not None and _PROCESS.poll() is None
        return {
            "loaded": bool(alive and _READY),
            "worker_alive": alive,
            "voices_loaded": (_READY or {}).get("voices_loaded", 0),
            "model": (_READY or {}).get("model", ""),
        }
