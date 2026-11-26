"""Persistent KittenTTS Pico bridge for JARVIS.

The bundled ONNX worker configures Misaki's English lexicon with NLTK POS
tagging and an eSpeak NG fallback. It deliberately avoids spaCy, PyTorch,
Transformers, and Kitten's optional BART G2P assets. JARVIS calls the worker
over localhost and copies each generated WAV into a unique cache file before
the worker's prior output is reclaimed.
"""
from __future__ import annotations

import json
import re
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 18765

_server_lock = threading.Lock()
_request_lock = threading.Lock()
_worker_proc = None
EXPECTED_WORKER_BUILD = "kitten-sentence-pauses-v2"


class StaleKittenWorkerError(RuntimeError):
    """Raised when the persistent socket belongs to an older worker build."""


def _kitten_cache() -> Path:
    configured = os.environ.get("JARVIS_KITTEN_CACHE", "").strip()
    # Keep model weights inside the JARVIS tree by default. An explicit
    # JARVIS_KITTEN_CACHE remains available for users who choose another disk.
    return (
        Path(configured).expanduser().resolve()
        if configured
        else ROOT / "cache" / "huggingface"
    )


def _request(payload: dict, timeout: float = 180.0) -> dict:
    with socket.create_connection((HOST, PORT), timeout=min(timeout, 10.0)) as sock:
        sock.settimeout(timeout)
        with sock.makefile("rwb") as stream:
            stream.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            stream.flush()
            raw = stream.readline(1_000_001)

    if not raw:
        raise RuntimeError("KittenTTS worker disconnected without a response.")
    if len(raw) > 1_000_000:
        raise RuntimeError("KittenTTS worker response exceeded the size limit.")

    result = json.loads(raw.decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "KittenTTS request failed."))
    return result


def _ping() -> dict:
    result = _request({"action": "ping"}, timeout=3.0)
    build = result.get("worker_build")
    if build != EXPECTED_WORKER_BUILD:
        raise StaleKittenWorkerError(
            f"KittenTTS worker build is {build!r}; expected {EXPECTED_WORKER_BUILD!r}."
        )
    return result


def _worker_pids(worker: Path) -> list[int]:
    """Find only processes whose argv contains this exact worker script."""
    target = str(worker.resolve())
    matches: list[int] = []
    proc_root = Path("/proc")
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\\0")
            args = [item.decode("utf-8", "replace") for item in argv if item]
        except (OSError, PermissionError, ProcessLookupError):
            continue
        if any(arg == target for arg in args):
            matches.append(pid)
    return matches


def _port_is_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.25):
            return True
    except OSError:
        return False


def _stop_stale_worker(worker: Path) -> None:
    """Stop the stale bundled worker and wait until its socket is released."""
    pids = _worker_pids(worker)
    for pid in pids:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise RuntimeError(
                f"Cannot stop stale KittenTTS worker PID {pid}; refusing to "
                "launch a second worker on the same port."
            ) from exc

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not _port_is_open():
            return
        time.sleep(0.2)

    # A listener remains. Never start another model process or kill an
    # unidentified process: report the owner so startup can fail safely.
    remaining = _worker_pids(worker)
    owner = ", ".join(map(str, remaining)) if remaining else "unknown"
    raise RuntimeError(
        f"Stale KittenTTS worker still owns {HOST}:{PORT} after shutdown "
        f"(worker PID(s): {owner}). Refusing duplicate startup."
    )


def ensure_server(timeout: float = 180.0) -> dict:
    """Reuse an existing worker or launch one detached from JARVIS."""
    global _worker_proc

    try:
        return _ping()
    except Exception:
        pass

    with _server_lock:
        try:
            return _ping()
        except Exception:
            pass

        # The worker ships with JARVIS; users no longer need a separate
        # ~/KittenTTS checkout or external worker path.
        worker = ROOT / "voice" / "kitten_worker.py"
        if not worker.is_file():
            raise FileNotFoundError(f"Bundled KittenTTS worker is missing: {worker}")

        _stop_stale_worker(worker)

        log_dir = ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "kitten_tts_worker.log"
        env = os.environ.copy()
        # Keep the English POS-tagger corpus local to this JARVIS checkout.
        nltk_data_dir = ROOT / "cache" / "nltk_data"
        nltk_data_dir.mkdir(parents=True, exist_ok=True)
        env["NLTK_DATA"] = str(nltk_data_dir)
        cache_dir = _kitten_cache()
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            env["JARVIS_KITTEN_HOME"] = str(cache_dir)
        # Permit the first run to download the tiny Pico model. Offline mode
        # is opt-in once the model has been cached.
        if env.get("JARVIS_KITTEN_OFFLINE", "0").strip().lower() in {"1", "true", "yes", "on"}:
            env["HF_HUB_OFFLINE"] = "1"
        else:
            env.pop("HF_HUB_OFFLINE", None)

        with log_path.open("a", encoding="utf-8") as log:
            _worker_proc = subprocess.Popen(
                [sys.executable, str(worker)],
                cwd=str(ROOT),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )

        deadline = time.monotonic() + max(5.0, float(timeout))
        last_error = "worker did not become ready"
        while time.monotonic() < deadline:
            if _worker_proc.poll() is not None:
                try:
                    tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
                except OSError:
                    tail = []
                detail = "\n".join(tail)
                raise RuntimeError(
                    "KittenTTS worker exited during startup."
                    + (f"\n{detail}" if detail else "")
                )
            try:
                return _ping()
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.25)

        raise TimeoutError(
            f"KittenTTS worker did not become ready within {timeout:.0f}s: {last_error}"
        )


def warmup() -> dict:
    """The worker loads the model and warms ONNX before binding its socket."""
    return ensure_server()


PICO_VOICES = {
    "eleanor_en": "en", "edith_en": "en", "otis_en": "en", "frank_en": "en",
    "anna_de": "de", "mia_de": "de", "lukas_de": "de", "paul_de": "de",
    "sofia_es": "es", "elena_es": "es", "pablo_es": "es", "mateo_es": "es",
    "francesca_it": "it", "alessandro_it": "it", "giorgio_it": "it", "davide_it": "it",
    "juliana_pt": "pt", "larissa_pt": "pt", "gustavo_pt": "pt", "caio_pt": "pt",
    "olga_ru": "ru", "tatiana_ru": "ru", "sergei_ru": "ru", "alexei_ru": "ru",
    "priya_hi": "hi", "arjun_hi": "hi",
    "amelie_fr": "fr", "lea_fr": "fr", "theo_fr": "fr", "baptiste_fr": "fr",
}


def synth(text: str, speed: float = 0.88, voice: str | None = None) -> Path:
    """Generate a WAV with a selected built-in Pico voice for JARVIS playback."""
    text = str(text).strip()
    # Enforce spoken-text cleanup at the provider boundary as well as in the
    # shared speech pipeline, so direct Kitten callers cannot pronounce this pause.
    text = re.sub(r",\s*(?=sir\b)", " ", text, flags=re.IGNORECASE)
    # Kitten phonemization should receive the spoken proper name, not an initialism.
    text = re.sub(r"\bjarvis\b", "Jarvis", text, flags=re.IGNORECASE)
    if not text:
        raise ValueError("KittenTTS text cannot be empty.")
    speed = max(0.5, min(2.0, float(speed)))
    voice_id = (voice or os.environ.get("JARVIS_KITTEN_VOICE", "otis_en")).strip().lower()
    if voice_id not in PICO_VOICES:
        raise ValueError(
            f"Unsupported KittenTTS Pico voice {voice_id!r}; choose one of: "
            + ", ".join(PICO_VOICES)
        )
    language = PICO_VOICES[voice_id]
    voice_name = voice_id.rsplit("_", 1)[0]
    ensure_server()

    with _request_lock:
        result = _request(
            {
                "action": "generate",
                "text": text,
                "voice": voice_name,
                "language": language,
                "speed": speed,
            },
            timeout=180.0,
        )
        source = Path(result["path"])
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError(f"KittenTTS output WAV is missing: {source}")

        cache_dir = ROOT / "cache" / "kitten_tts"
        cache_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="otis-", suffix=".wav", dir=str(cache_dir))
        os.close(fd)
        target = Path(name)
        try:
            shutil.copyfile(source, target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target
