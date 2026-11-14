"""Persistent Kokoro-82M worker client for Android/Termux."""
from __future__ import annotations

import json
import os
import select
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "kokoro82m"
MODEL = MODEL_DIR / "model_q8f16.onnx"
VOICE_DIR = MODEL_DIR / "voices"
WORKER_DIR = ROOT / "voice" / "kokoro_worker"
WORKER = WORKER_DIR / "target" / "release" / "jarvis-kokoro-worker"
_LOCK = threading.RLock()
_PROCESS = None
_READY = None
_LOG = None
_VALID_VOICES = {
    "af_alloy","af_aoede","af_bella","af_heart","af_jessica","af_kore","af_nicole","af_nova","af_river","af_sarah","af_sky",
    "am_adam","am_echo","am_eric","am_fenrir","am_liam","am_michael","am_onyx","am_puck","am_santa",
    "bf_alice","bf_emma","bf_isabella","bf_lily","bm_daniel","bm_fable","bm_george","bm_lewis",
    "ef_dora","em_alex","em_santa","ff_siwis","hf_alpha","hf_beta","hm_omega","hm_psi",
    "if_sara","im_nicola","jf_alpha","jf_gongitsune","jf_nezumi","jf_tebukuro","jm_kumo",
    "pf_dora","pm_alex","pm_santa","zf_xiaobei","zf_xiaoni","zf_xiaoxiao","zf_xiaoyi",
    "zm_yunjian","zm_yunxi","zm_yunxia","zm_yunyang","jarvis_nicole30",
}

def _readline(stream, timeout: float) -> str:
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        raise TimeoutError(f"Kokoro worker did not respond within {timeout:.0f}s")
    line = stream.readline()
    if not line:
        raise RuntimeError("Kokoro worker exited unexpectedly")
    return line

def _start_worker() -> dict:
    global _PROCESS, _READY, _LOG
    if _PROCESS is not None and _PROCESS.poll() is None and _READY:
        return _READY
    if not MODEL.is_file() or not VOICE_DIR.is_dir():
        raise RuntimeError("Kokoro assets missing; run: bash scripts/install_kokoro82m_termux.sh")
    missing = [name for name in _VALID_VOICES if not (VOICE_DIR / f"{name}.bin").is_file()]
    if missing:
        raise RuntimeError("Kokoro voice assets missing; rerun installer: " + ", ".join(sorted(missing)[:5]))
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "jarvis"
    cache.mkdir(parents=True, exist_ok=True)
    _LOG = (cache / "kokoro_worker.log").open("a", encoding="utf-8")
    worker_env = os.environ.copy()
    try:
        import onnxruntime
        ort_root = Path(onnxruntime.__file__).resolve().parent
        candidates = [
            ort_root / "capi" / "libonnxruntime.so",
            Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr")) / "lib" / "libonnxruntime.so",
        ]
        ort_library = next((path for path in candidates if path.is_file()), None)
        if ort_library is not None:
            worker_env["ORT_STRATEGY"] = "system"
            worker_env["ORT_DYLIB_PATH"] = str(ort_library)
            current_ld = worker_env.get("LD_LIBRARY_PATH", "")
            worker_env["LD_LIBRARY_PATH"] = str(ort_library.parent) + (":" + current_ld if current_ld else "")
    except Exception:
        pass
    _PROCESS = subprocess.Popen(
        [str(WORKER), str(MODEL), str(VOICE_DIR)],
        cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=_LOG, text=True, bufsize=1, start_new_session=True,
        env=worker_env,
    )
    try:
        payload = json.loads(_readline(_PROCESS.stdout, 300.0))
        if not payload.get("ready") or payload.get("voices_loaded", 0) < 54:
            raise RuntimeError(f"Kokoro worker failed startup validation: {payload}")
        _READY = payload
        return payload
    except Exception:
        try:
            _PROCESS.terminate()
            _PROCESS.wait(timeout=2)
        except Exception:
            pass
        _PROCESS = _READY = None
        raise

def warmup() -> bool:
    payload = _start_worker()
    print(
        "[TTS] Kokoro-82M persistent worker preloaded; "
        f"{payload['voices_loaded']} voices resident; "
        f"warmup {payload.get('warmup_ms')} ms.",
        flush=True,
    )
    return True

def synth(text: str, voice: str | None = None, speed: float = 1.0) -> Path:
    text = " ".join(str(text or "").split())
    if not text:
        raise RuntimeError("Kokoro received empty text.")
    selected = (voice or os.environ.get("JARVIS_KOKORO_VOICE", "jarvis_nicole30")).strip()
    if selected not in _VALID_VOICES:
        raise RuntimeError(f"Unknown Kokoro voice {selected!r}.")
    speed = max(0.5, min(2.0, float(speed)))
    with _LOCK:
        _start_worker()
        out_dir = Path(tempfile.gettempdir()) / "jarvis-kokoro"
        out_dir.mkdir(parents=True, exist_ok=True)
        fd, filename = tempfile.mkstemp(prefix="speech-", suffix=".wav", dir=str(out_dir))
        os.close(fd)
        output = Path(filename)
        output.unlink(missing_ok=True)
        request = {"text": text, "voice": selected, "speed": speed, "output": str(output)}
        try:
            _PROCESS.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            _PROCESS.stdin.flush()
            result = json.loads(_readline(_PROCESS.stdout, 240.0))
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Kokoro synthesis failed"))
            if not output.is_file() or output.stat().st_size <= 44:
                raise RuntimeError("Kokoro worker reported success but produced no WAV.")
            return output
        except Exception:
            output.unlink(missing_ok=True)
            raise

def interrupt() -> None:
    # The shared inference worker remains loaded; playback cancellation is handled
    # by TTSManager's generation token and mpv process.
    return None

def status() -> dict:
    with _LOCK:
        alive = _PROCESS is not None and _PROCESS.poll() is None
        return {"loaded": bool(alive and _READY), "worker_alive": alive, "voices_loaded": (_READY or {}).get("voices_loaded", 0)}
