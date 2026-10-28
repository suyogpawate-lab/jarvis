"""Client adapter for JARVIS's shared, persistently warmed Phonon service.

The service owns the Rust worker and checkpoint. CLI, HTTP bridge, and voice
listener clients talk to the same localhost endpoint instead of each loading
another model into memory.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "voice" / "phonon_worker"
WORKER_BIN = WORKER_DIR / "target" / "release" / "jarvis-phonon-worker"
SERVER_SCRIPT = ROOT / "voice" / "phonon_server.py"
HOST = "127.0.0.1"
PORT = 21342
BASE_URL = f"http://{HOST}:{PORT}"
VALID_VOICES = {"edwin", "toby", "aldric", "trevor", "hugh", "spencer", "bramwell", "default"}
_PROCESS_LOCK = threading.Lock()
_GENERATION = 0


def _load_env() -> None:
    try:
        from jarvis_env import load_env
        load_env()
    except (ImportError, OSError):
        pass


def model_dir() -> Path:
    configured = os.environ.get("JARVIS_PHONON_DIR", "").strip()
    candidates = (
        [Path(configured).expanduser()]
        if configured
        else [Path.home() / "phonon-model", ROOT / "models" / "phonon"]
    )
    for candidate in candidates:
        if candidate and all(
            (candidate / filename).is_file()
            for filename in ("config.json", "tokenizer.json", "model.q8.gguf")
        ):
            return candidate
    expected = Path(configured).expanduser() if configured else Path.home() / "phonon-model"
    raise RuntimeError(
        f"Phonon checkpoint is incomplete at {expected}. Run: "
        "python scripts/prepare_phonon_assets.py (or bash install.sh --with-phonon)."
    )


def _voice_and_quant(directory: Path) -> tuple[str, str]:
    voice = os.environ.get("JARVIS_PHONON_VOICE", "edwin").strip().lower() or "edwin"
    if voice not in VALID_VOICES:
        voice = "edwin"
    if voice != "default" and not (directory / "voices" / f"{voice}.safetensors").is_file():
        raise RuntimeError(
            f"Phonon voice '{voice}' is missing from {directory / 'voices'}. "
            "Run: python scripts/prepare_phonon_assets.py"
        )
    if voice == "default" and not (directory / "default-voice.safetensors").is_file():
        raise RuntimeError(f"Phonon default voice is missing from {directory}")
    quant = os.environ.get("JARVIS_PHONON_QUANT", "q8").strip() or "q8"
    return voice, quant


def _build_worker() -> Path:
    # Rebuild when the Rust protocol changes; an old release binary may not
    # understand per-request voice selection even though it still exists.
    if WORKER_BIN.is_file():
        binary_mtime = WORKER_BIN.stat().st_mtime
        inputs = [WORKER_DIR / "Cargo.toml", WORKER_DIR / "Cargo.lock"]
        inputs.extend((WORKER_DIR / "src").glob("*.rs"))
        if not any(path.is_file() and path.stat().st_mtime > binary_mtime for path in inputs):
            return WORKER_BIN
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
    if not Path(cargo).is_file():
        raise RuntimeError("Cargo is unavailable; cannot build the persistent Phonon worker.")
    build_env = os.environ.copy()
    build_env.setdefault("CARGO_HTTP_TIMEOUT", "180")
    build_env.setdefault("CARGO_HTTP_LOW_SPEED_LIMIT", "1")
    build_env.setdefault("CARGO_NET_RETRY", "3")
    result = subprocess.run(
        [cargo, "build", "--release", "--manifest-path", str(WORKER_DIR / "Cargo.toml")],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=900,
        check=False,
        env=build_env,
    )
    if result.returncode != 0 or not WORKER_BIN.is_file():
        detail = (result.stdout or "no build output").strip()[-1200:]
        raise RuntimeError(f"Could not build the persistent Phonon worker: {detail}")
    return WORKER_BIN


def _health(timeout: float = 0.75) -> dict | None:
    try:
        request = urllib.request.Request(BASE_URL + "/health", headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.2):
            return True
    except OSError:
        return False


def _validate_service(payload: dict) -> None:
    expected_dir = str(model_dir())
    _voice, expected_quant = _voice_and_quant(Path(expected_dir))
    if payload.get("model_dir") != expected_dir or payload.get("quant") != expected_quant:
        raise RuntimeError(
            "A Phonon service is already running with a different model configuration. "
            f"Running model={payload.get('model_dir')!r}, quant={payload.get('quant')!r}; "
            f"requested model={expected_dir!r}, quant={expected_quant!r}."
        )
    if not payload.get("ready") or not payload.get("warmup_verified"):
        raise RuntimeError("Phonon service is responding but its model warmup is not verified.")


def ensure_server(timeout: float = 960.0) -> dict:
    """Ensure exactly one shared service is running and has passed inference warmup."""
    _load_env()
    directory = model_dir()
    _voice, quant = _voice_and_quant(directory)
    prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    temp_dir = prefix / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    lock_path = temp_dir / "jarvis-phonon-service.lock"
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "jarvis"
    cache.mkdir(parents=True, exist_ok=True)
    log_path = cache / "phonon_server.log"

    # flock is process-wide, so separate JARVIS processes cannot race to load
    # duplicate models while the first service is still warming up.
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        payload = _health()
        if payload and payload.get("ready"):
            _validate_service(payload)
            return payload

        launched = False
        deadline = time.monotonic() + max(1.0, timeout)
        while time.monotonic() < deadline:
            payload = _health()
            if payload and payload.get("ready"):
                _validate_service(payload)
                return payload

            if not launched and not _port_open():
                with log_path.open("a", encoding="utf-8") as log:
                    subprocess.Popen(
                        [sys.executable, str(SERVER_SCRIPT)],
                        cwd=str(ROOT),
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                        close_fds=True,
                        env=os.environ.copy(),
                    )
                launched = True
            time.sleep(0.5)

    try:
        tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-35:])
    except OSError:
        tail = "(Phonon service log is unavailable.)"
    raise RuntimeError(
        f"Shared Phonon service did not pass model initialization and real synthesis warmup "
        f"within {timeout:.0f} seconds. Log: {log_path}\n{tail}"
    )


def warmup() -> bool:
    """Wait until the shared service has loaded the model and passed real inference."""
    payload = ensure_server()
    print(
        "[TTS] Phonon shared service ready; real synthesis warmup verified; "
        f"worker PID {payload.get('worker_pid')}; memory {payload.get('worker_memory', {})}.",
        flush=True,
    )
    return True


def synth(text: str) -> Path:
    """Synthesize through the shared worker and return a local temporary WAV path."""
    global _GENERATION
    _load_env()
    text = " ".join(str(text or "").split())
    if not text:
        raise RuntimeError("Phonon received empty text.")
    directory = model_dir()
    voice, _quant = _voice_and_quant(directory)
    with _PROCESS_LOCK:
        generation = _GENERATION

    ensure_server()
    request = urllib.request.Request(
        BASE_URL + "/speak",
        data=json.dumps({"text": text, "voice": voice}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=190.0) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace")).get("error", str(exc))
        except (ValueError, AttributeError):
            detail = str(exc)
        with _PROCESS_LOCK:
            interrupted = generation != _GENERATION
        if interrupted:
            raise RuntimeError("Phonon synthesis was interrupted.") from exc
        raise RuntimeError(f"Phonon service failed: {detail}") from exc
    except (OSError, urllib.error.URLError) as exc:
        with _PROCESS_LOCK:
            interrupted = generation != _GENERATION
        if interrupted:
            raise RuntimeError("Phonon synthesis was interrupted.") from exc
        raise RuntimeError(f"Could not contact the shared Phonon service: {exc}") from exc

    with _PROCESS_LOCK:
        interrupted = generation != _GENERATION
    if interrupted:
        raise RuntimeError("Phonon synthesis was interrupted.")
    if len(audio) <= 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise RuntimeError("Shared Phonon service returned invalid WAV audio.")

    prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    temp_dir = prefix / "tmp"
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        temp_dir = Path(tempfile.gettempdir())
    fd, filename = tempfile.mkstemp(prefix="jarvis-phonon-", suffix=".wav", dir=str(temp_dir))
    output = Path(filename)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(audio)
        return output
    except Exception:
        output.unlink(missing_ok=True)
        raise


def interrupt() -> None:
    """Cancel active inference; the service reloads and re-warms only if interrupted."""
    global _GENERATION
    with _PROCESS_LOCK:
        _GENERATION += 1
    try:
        request = urllib.request.Request(BASE_URL + "/interrupt", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=1.5) as response:
            response.read()
    except (OSError, urllib.error.URLError):
        pass
