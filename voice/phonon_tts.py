"""Persistent Phonon TTS adapter for JARVIS.

The preferred path runs a small Rust worker that loads the Phonon checkpoint once
and accepts newline-delimited JSON synthesis requests. If the worker cannot be
built, the adapter falls back to the ptts CLI so older installs remain usable.
"""
from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "voice" / "phonon_worker"
WORKER_BIN = WORKER_DIR / "target" / "release" / "jarvis-phonon-worker"
VALID_VOICES = {"edwin", "toby", "aldric", "trevor", "hugh", "spencer", "bramwell", "default"}
_PROCESS_LOCK = threading.Lock()
_WORKER_LOCK = threading.RLock()
_ACTIVE_PROCESS = None
_WORKER_PROCESS = None
_WORKER_CONFIG = None
_WORKER_BUSY = False
_GENERATION = 0


def interrupt() -> None:
    """Cancel active synthesis. The worker is restarted only if it was busy."""
    global _GENERATION, _WORKER_PROCESS, _WORKER_CONFIG, _ACTIVE_PROCESS, _WORKER_BUSY
    with _PROCESS_LOCK:
        _GENERATION += 1
        process = _ACTIVE_PROCESS if _WORKER_BUSY else None
        if process is not None:
            _ACTIVE_PROCESS = None
            _WORKER_BUSY = False
            _WORKER_PROCESS = None
            _WORKER_CONFIG = None
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except OSError:
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


def _exe() -> str:
    exe = shutil.which("ptts") or str(Path.home() / ".cargo" / "bin" / "ptts")
    if not Path(exe).is_file():
        raise RuntimeError(
            "Phonon CLI 'ptts' not found. Run: cargo install ptts --locked --features cli"
        )
    return exe


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
    if WORKER_BIN.is_file():
        return WORKER_BIN
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
    if not Path(cargo).is_file():
        raise RuntimeError("Cargo is unavailable; cannot build the persistent Phonon worker.")
    # Android networks can be very slow to fetch crates. Keep retries bounded;
    # this build is started by background warmup, never as a prerequisite for
    # speaking the current response.
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


def _readline_timeout(process, timeout: float) -> str:
    if process.stdout is None:
        raise RuntimeError("Phonon worker stdout is unavailable.")
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    if not ready:
        raise RuntimeError(f"Phonon worker timed out after {timeout:.0f} seconds.")
    line = process.stdout.readline()
    if not line:
        raise RuntimeError("Phonon worker exited before replying.")
    return line


def _ensure_worker(directory: Path, voice: str, quant: str):
    global _WORKER_PROCESS, _WORKER_CONFIG, _ACTIVE_PROCESS
    config = (str(directory), voice, quant)
    with _WORKER_LOCK:
        if _WORKER_PROCESS is not None and _WORKER_PROCESS.poll() is None and _WORKER_CONFIG == config:
            return _WORKER_PROCESS
        _stop_worker_locked()
        binary = _build_worker()
        process = subprocess.Popen(
            [str(binary), str(directory), voice, quant],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
        )
        with _PROCESS_LOCK:
            _ACTIVE_PROCESS = process
        try:
            ready = json.loads(_readline_timeout(process, 900))
            if not ready.get("ready"):
                raise RuntimeError(ready.get("error", "Phonon worker did not report ready."))
        except Exception:
            if process.poll() is None:
                process.terminate()
            with _PROCESS_LOCK:
                if _ACTIVE_PROCESS is process:
                    _ACTIVE_PROCESS = None
            raise
        with _PROCESS_LOCK:
            if _ACTIVE_PROCESS is process:
                _ACTIVE_PROCESS = None
        _WORKER_PROCESS = process
        _WORKER_CONFIG = config
        return process


def _stop_worker_locked() -> None:
    global _WORKER_PROCESS, _WORKER_CONFIG, _ACTIVE_PROCESS, _WORKER_BUSY
    process = _WORKER_PROCESS
    _WORKER_PROCESS = None
    _WORKER_CONFIG = None
    with _PROCESS_LOCK:
        if _ACTIVE_PROCESS is process:
            _ACTIVE_PROCESS = None
        _WORKER_BUSY = False
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass


def warmup() -> bool:
    """Build (if needed) and start the worker so its model is ready in the background."""
    directory = model_dir()
    voice, quant = _voice_and_quant(directory)
    _ensure_worker(directory, voice, quant)
    return True


def _synth_cli(text: str, directory: Path, voice: str, quant: str) -> Path:
    prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    temp_dir = prefix / "tmp"
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        temp_dir = Path(tempfile.gettempdir())
    fd, filename = tempfile.mkstemp(prefix="jarvis-phonon-", suffix=".wav", dir=str(temp_dir))
    os.close(fd)
    output = Path(filename)
    output.unlink(missing_ok=True)
    command = [
        _exe(), "--model", str(directory), "--voice", voice,
        "--quant", quant, "--lang", "en",
    ]
    threads = os.environ.get("JARVIS_PHONON_THREADS", "").strip()
    if threads.isdigit() and int(threads) > 0:
        command += ["--threads", str(int(threads))]
    command += [text, "-o", str(output)]
    process = None
    try:
        with _PROCESS_LOCK:
            generation = _GENERATION
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            global _ACTIVE_PROCESS
            _ACTIVE_PROCESS = process
        try:
            stdout, stderr = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError("ptts exceeded the 180-second synthesis timeout.")
        with _PROCESS_LOCK:
            interrupted = generation != _GENERATION
        if interrupted:
            raise RuntimeError("Phonon synthesis was interrupted.")
        if process.returncode or not output.is_file() or output.stat().st_size == 0:
            detail = (stderr or stdout or "no diagnostic output").strip()[-300:]
            raise RuntimeError(f"ptts failed (exit {process.returncode}): {detail}")
        return output
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
        with _PROCESS_LOCK:
            if _ACTIVE_PROCESS is process:
                _ACTIVE_PROCESS = None


def synth(text: str) -> Path:
    text = " ".join(str(text or "").split())
    if not text:
        raise RuntimeError("Phonon received empty text.")
    directory = model_dir()
    voice, quant = _voice_and_quant(directory)

    # Startup warmup holds this lock while compiling the worker and loading
    # the model. Acquire it BEFORE checking the binary: otherwise every early
    # utterance can bypass an in-progress preheat and cold-start the ptts CLI.
    _WORKER_LOCK.acquire()
    try:
        # If warmup has finished unsuccessfully (or was never started), retain
        # the legacy CLI fallback. While warmup is active, the lock above makes
        # synthesis wait until the persistent worker is ready.
        if not WORKER_BIN.is_file():
            return _synth_cli(text, directory, voice, quant)

        prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
        temp_dir = prefix / "tmp"
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            temp_dir = Path(tempfile.gettempdir())
        fd, filename = tempfile.mkstemp(prefix="jarvis-phonon-", suffix=".wav", dir=str(temp_dir))
        os.close(fd)
        output = Path(filename)
        output.unlink(missing_ok=True)

        global _WORKER_BUSY, _ACTIVE_PROCESS, _WORKER_PROCESS, _WORKER_CONFIG
        generation = None
        try:
            try:
                with _WORKER_LOCK:
                    process = _ensure_worker(directory, voice, quant)
                    with _PROCESS_LOCK:
                        generation = _GENERATION
                        _WORKER_BUSY = True
                        _ACTIVE_PROCESS = process
                    if process.stdin is None:
                        raise RuntimeError("Phonon worker stdin is unavailable.")
                    process.stdin.write(json.dumps({"text": text, "output": str(output)}) + "\n")
                    process.stdin.flush()
                    response = json.loads(_readline_timeout(process, 180))
                    with _PROCESS_LOCK:
                        interrupted = generation != _GENERATION
                        if _ACTIVE_PROCESS is process:
                            _ACTIVE_PROCESS = None
                        _WORKER_BUSY = False
                    if interrupted:
                        raise RuntimeError("Phonon synthesis was interrupted.")
                    if not response.get("ok"):
                        raise RuntimeError(response.get("error", "Phonon worker synthesis failed."))
                    if not output.is_file() or output.stat().st_size == 0:
                        raise RuntimeError("Phonon worker reported success but produced no WAV.")
                    return output
            except Exception as exc:
                # Never turn an explicit cancellation into a new, unwanted CLI synthesis.
                with _PROCESS_LOCK:
                    was_interrupted = generation is not None and generation != _GENERATION
                if was_interrupted or "interrupted" in str(exc).lower():
                    raise RuntimeError("Phonon synthesis was interrupted.") from exc
                # Keep the legacy CLI as a recovery path when the helper cannot be built,
                # started, or complete a request. Playback has not started yet.
                with _PROCESS_LOCK:
                    _WORKER_BUSY = False
                    _ACTIVE_PROCESS = None
                if _WORKER_PROCESS is not None and _WORKER_PROCESS.poll() is not None:
                    _WORKER_PROCESS = None
                    _WORKER_CONFIG = None
                output.unlink(missing_ok=True)
                return _synth_cli(text, directory, voice, quant)
        except Exception:
            output.unlink(missing_ok=True)
            raise

    finally:
        _WORKER_LOCK.release()
