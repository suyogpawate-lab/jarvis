"""Optional local dual-voice Piper models running through sherpa-onnx.

Model weights are downloaded on demand by scripts/prepare_sherpa_assets.py.
The inference and playback API matches the existing TTSManager provider contract.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_lock = threading.RLock()
_engines = {}
_active_process = None


def _paths(voice: str) -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1]
    folders = {
        "alan": ("en_GB-alan-medium", "en/en_GB/alan/medium"),
        "bryce": ("en_US-bryce-medium", "en/en_US/bryce/medium"),
    }
    if voice not in folders:
        voice = "alan"
    model_name, _ = folders[voice]
    directory = root / "models" / "sherpa" / voice
    prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    configured_espeak = os.environ.get("JARVIS_ESPEAK_DATA", "").strip()
    candidates = []
    if configured_espeak:
        candidates.append(Path(configured_espeak).expanduser())
    candidates.extend([
        root / "voice" / "data" / "espeak-ng-data",
        prefix / "share" / "espeak-ng-data",
    ])
    espeak = next(
        (candidate for candidate in candidates if candidate.is_dir() and any(candidate.iterdir())),
        candidates[0],
    )
    return {
        "model": directory / (model_name + ".onnx"),
        "tokens": directory / "tokens.txt",
        "data": espeak,
        "output": root / "cache" / "sherpa",
    }


def _engine(voice: str):
    voice = voice if voice in ("alan", "bryce") else "alan"
    with _lock:
        if voice in _engines:
            return _engines[voice]
        paths = _paths(voice)
        missing = [str(paths[k]) for k in ("model", "tokens") if not paths[k].is_file()]
        if missing:
            raise RuntimeError(
                "Sherpa voice files are missing. Run: python scripts/prepare_sherpa_assets.py "
                + voice + " (missing: " + ", ".join(missing) + ")"
            )
        if not paths["data"].is_dir() or not any(paths["data"].iterdir()):
            raise RuntimeError(
                "eSpeak NG data is missing. Install it with 'pkg install espeak-ng', "
                "or set JARVIS_ESPEAK_DATA to its data directory."
            )
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "sherpa-onnx is not installed in this Python environment. "
                "Install a Termux-compatible sherpa-onnx build before selecting the Sherpa provider."
            ) from exc
        settings = {
            "alan": {"noise_scale": 0.667, "noise_scale_w": 0.8, "length_scale": 0.92},
            "bryce": {"noise_scale": 0.70, "noise_scale_w": 0.85, "length_scale": 0.95},
        }[voice]
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(paths["model"]),
                    tokens=str(paths["tokens"]),
                    data_dir=str(paths["data"]),
                    noise_scale=settings["noise_scale"],
                    noise_scale_w=settings["noise_scale_w"],
                    length_scale=settings["length_scale"],
                ),
                num_threads=max(1, min(4, os.cpu_count() or 2)),
                debug=False,
                provider="cpu",
            )
        )
        engine = sherpa_onnx.OfflineTts(config)
        _engines[voice] = engine
        return engine


def interrupt() -> None:
    global _active_process
    with _lock:
        proc = _active_process
        _active_process = None
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


def _speak_local(text: str, wait: bool = True, speed: float = 1.0, voice: str | None = None):
    global _active_process
    text = str(text or "").strip()
    if not text:
        return False
    if not shutil.which("mpv"):
        raise RuntimeError("mpv is not installed or not on PATH.")
    selected = (voice or os.environ.get("JARVIS_SHERPA_VOICE", "alan")).strip().lower()
    if selected not in ("alan", "bryce"):
        selected = "alan"
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile is required for Sherpa TTS; install it in the active Python environment.") from exc

    engine = _engine(selected)
    paths = _paths(selected)
    paths["output"].mkdir(parents=True, exist_ok=True)
    audio = engine.generate(text, sid=0, speed=max(0.5, min(2.0, float(speed))))
    samples = getattr(audio, "samples", None)
    if samples is None or len(samples) == 0:
        raise RuntimeError("Sherpa returned no audio samples.")
    fd, name = tempfile.mkstemp(prefix="speech-", suffix=".wav", dir=str(paths["output"]))
    os.close(fd)
    audio_path = Path(name)
    sf.write(str(audio_path), samples, audio.sample_rate)
    command = ["mpv", "--no-video", "--no-terminal", "--really-quiet", "--", str(audio_path)]
    with _lock:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _active_process = proc
    if not wait:
        return proc
    try:
        result = proc.wait()
        if result != 0:
            raise RuntimeError(f"mpv exited with status {result}")
        return True
    finally:
        audio_path.unlink(missing_ok=True)
        with _lock:
            if _active_process is proc:
                _active_process = None


_server_lock = threading.Lock()
_server_process = None


def _server_url() -> str:
    return f"http://127.0.0.1:{int(os.environ.get('JARVIS_TTS_SERVER_PORT', '21342'))}"


def _server_healthy(timeout: float = 0.5) -> bool:
    try:
        request = urllib.request.Request(_server_url() + "/health", method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("ok") and payload.get("service") == "jarvis-sherpa-tts")
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _ensure_server() -> None:
    global _server_process
    if _server_healthy():
        return
    with _server_lock:
        if _server_healthy():
            return
        root = Path(__file__).resolve().parents[1]
        _server_process = subprocess.Popen(
            [sys.executable, "-m", "voice.sherpa_server"],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if _server_healthy():
                return
            if _server_process.poll() is not None:
                break
            time.sleep(0.25)
    raise RuntimeError("Local Sherpa TTS server did not become ready. Check sherpa-onnx, soundfile, model assets, and port 21342.")


def speak(text: str, wait: bool = True, speed: float = 1.0, voice: str | None = None):
    """Send speech to the persistent localhost service; Piper models stay cached."""
    text = str(text or "").strip()
    if not text:
        return False
    selected = (voice or os.environ.get("JARVIS_SHERPA_VOICE", "alan")).strip().lower()
    if selected not in ("alan", "bryce"):
        selected = "alan"
    _ensure_server()
    body = json.dumps({"voice": selected, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        _server_url() + "/speak",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300 if wait else 2) as response:
            result = json.loads(response.read().decode("utf-8"))
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Local Sherpa TTS failed"))
            return True
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
        except Exception:
            detail = ""
        raise RuntimeError(f"Local Sherpa TTS HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Local Sherpa TTS request failed: {exc.reason}") from exc
