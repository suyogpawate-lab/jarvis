"""Persistent dual-pack Kokoro worker client used by JARVIS TTSManager."""
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
MODEL_V1 = MODEL_DIR / "kokoro-v1.0.fp16.onnx"
VOICES_V1 = MODEL_DIR / "voices-v1.0.bin"
MODEL_V11 = MODEL_DIR / "kokoro-v1.1-zh.fp16.onnx"
VOICES_V11 = MODEL_DIR / "voices-v1.1-zh.bin"
WORKER = ROOT / "scripts" / "kokoro_worker.py"
_LOCK = threading.RLock()
_PROCESS = None
_READY = None
_LOG = None


def _selected_voice() -> str:
    return os.environ.get("JARVIS_KOKORO_NORMAL_VOICE", "am_eric").strip() or "am_eric"


def model_for_voice(voice: str | None = None) -> Path:
    """Return the matching ONNX pack without loading it."""
    selected = (voice or _selected_voice()).strip()
    if selected.startswith(("zf_", "zm_")) or selected in ("af_maple", "af_sol", "bf_vale"):
        return MODEL_V11
    return MODEL_V1


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
    selected = _selected_voice()
    if _PROCESS is not None and _PROCESS.poll() is None and _READY:
        if _READY.get("selected_voice") != selected:
            raise RuntimeError(
                "Kokoro voice selection changed while its worker was running. Restart JARVIS to preload the new voice."
            )
        return _READY
    required = (MODEL_V1, VOICES_V1, MODEL_V11, VOICES_V11)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Kokoro 157-voice assets are missing: " + ", ".join(missing)
            + "; run: bash scripts/install_kokoro82m_termux.sh"
        )
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "jarvis"
    cache.mkdir(parents=True, exist_ok=True)
    _LOG = (cache / "kokoro_worker.log").open("a", encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("OMP_NUM_THREADS", os.environ.get("JARVIS_KOKORO_THREADS", "2"))
    _PROCESS = subprocess.Popen(
        [
            sys.executable, str(WORKER),
            str(MODEL_V1), str(VOICES_V1), str(MODEL_V11), str(VOICES_V11), selected,
        ],
        cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=_LOG, text=True, bufsize=1, env=env, start_new_session=True,
    )
    try:
        ready = json.loads(_readline(_PROCESS.stdout, 360.0))
        if (
            not ready.get("ready")
            or ready.get("voices_loaded", 0) != 157
            or ready.get("selected_voice") != selected
            or not ready.get("normal_style_preloaded")
            or not ready.get("whisper_style_preloaded")
        ):
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
    with _LOCK:
        ready = _start_worker()
    print(
        "[TTS] Kokoro-82M persistent worker ready; "
        f"{ready['voices_loaded']} voices available; selected={ready['selected_voice']}; "
        f"model={ready['model_family']}; normal + matching whisper styles preloaded; "
        f"model load {ready.get('model_load_seconds')}s; inference warmup complete.",
        flush=True,
    )
    return True


def synth(text: str, voice: str | None = None, speed: float = 1.0) -> Path:
    text = " ".join(str(text or "").split())
    if not text:
        raise RuntimeError("Kokoro received empty text.")
    selected = (voice or _selected_voice()).strip()
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
    # Keep the selected ONNX session and both speaker-style arrays resident.
    return None


def status() -> dict:
    with _LOCK:
        alive = _PROCESS is not None and _PROCESS.poll() is None
        return {
            "loaded": bool(alive and _READY),
            "worker_alive": alive,
            "voices_loaded": (_READY or {}).get("voices_loaded", 0),
            "selected_voice": (_READY or {}).get("selected_voice", _selected_voice()),
            "model_family": (_READY or {}).get("model_family", ""),
            "model_path": (_READY or {}).get("model_path", str(model_for_voice())),
            "normal_style_preloaded": bool((_READY or {}).get("normal_style_preloaded")),
            "whisper_style_preloaded": bool((_READY or {}).get("whisper_style_preloaded")),
        }
