"""Phonon TTS adapter with a persistent, preloaded Python runtime when available.

Set JARVIS_PHONON_DIR to override the default ~/phonon-model directory.
The checkpoint and voice embeddings are installed by scripts/prepare_phonon_assets.py.
If the optional Python bindings cannot be loaded, synthesis falls back to the ptts CLI.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID_VOICES = {"edwin", "toby", "aldric", "trevor", "hugh", "spencer", "bramwell", "default"}
_PROCESS_LOCK = threading.Lock()
_ACTIVE_PROCESS = None
_GENERATION = 0

_WORKER_LOCK = threading.Lock()
_WORKER_PROCESS = None
_WORKER_RESPONSES = None
_WORKER_UNAVAILABLE = False
_WORKER_BUSY = False


class PersistentWorkerUnavailable(RuntimeError):
    """Raised when the optional persistent Python binding cannot start."""


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


def _selected_voice(directory: Path | None = None) -> str:
    directory = directory or model_dir()
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
    return voice


def _exe() -> str:
    exe = shutil.which("ptts") or str(Path.home() / ".cargo" / "bin" / "ptts")
    if not Path(exe).is_file():
        raise RuntimeError(
            "Phonon CLI 'ptts' not found. Run: cargo install ptts --locked --features cli"
        )
    return exe


def _worker_reader(process, responses):
    try:
        for line in process.stdout:
            responses.put(line)
    finally:
        responses.put(None)


def _next_worker_message(responses, timeout: float) -> dict:
    try:
        line = responses.get(timeout=timeout)
    except queue.Empty as exc:
        raise PersistentWorkerUnavailable("Timed out waiting for the Phonon worker.") from exc
    if line is None:
        raise PersistentWorkerUnavailable("Phonon worker exited before replying.")
    try:
        return json.loads(line)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PersistentWorkerUnavailable("Phonon worker returned invalid protocol data.") from exc


def _ensure_worker_locked() -> None:
    """Start the model worker once; caller must hold _WORKER_LOCK."""
    global _WORKER_PROCESS, _WORKER_RESPONSES, _WORKER_UNAVAILABLE
    if _WORKER_UNAVAILABLE:
        raise PersistentWorkerUnavailable("Persistent Phonon Python bindings are unavailable.")
    if _WORKER_PROCESS is not None and _WORKER_PROCESS.poll() is None:
        return

    responses = queue.Queue()
    try:
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "voice.phonon_worker"],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        _WORKER_UNAVAILABLE = True
        raise PersistentWorkerUnavailable(f"Could not start Phonon worker: {exc}") from exc

    _WORKER_PROCESS = process
    _WORKER_RESPONSES = responses
    threading.Thread(
        target=_worker_reader, args=(process, responses), daemon=True, name="PhononWorkerReader"
    ).start()
    try:
        ready = _next_worker_message(responses, 180.0)
    except PersistentWorkerUnavailable:
        process.terminate()
        _WORKER_UNAVAILABLE = True
        raise
    if not ready.get("ready"):
        error = str(ready.get("error", "unknown startup error"))
        process.terminate()
        _WORKER_UNAVAILABLE = True
        raise PersistentWorkerUnavailable(error)


def warmup() -> bool:
    """Start Phonon and load its model in the background, if Python bindings exist."""
    with _WORKER_LOCK:
        _ensure_worker_locked()
    return True


def _request_worker(text: str, output: Path) -> Path:
    global _WORKER_BUSY
    with _WORKER_LOCK:
        _ensure_worker_locked()
        process = _WORKER_PROCESS
        responses = _WORKER_RESPONSES
        if process is None or process.stdin is None:
            raise PersistentWorkerUnavailable("Phonon worker has no input stream.")
        with _PROCESS_LOCK:
            _WORKER_BUSY = True
            generation = _GENERATION
        try:
            process.stdin.write(json.dumps({
                "op": "speak", "text": text, "output": str(output)
            }) + "\n")
            process.stdin.flush()
            response = _next_worker_message(responses, 180.0)
            with _PROCESS_LOCK:
                interrupted = generation != _GENERATION
            if interrupted:
                raise RuntimeError("Phonon synthesis was interrupted.")
            if not response.get("ok"):
                raise RuntimeError(str(response.get("error", "Phonon worker synthesis failed.")))
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError("Persistent Phonon worker produced no WAV output.")
            return output
        except PersistentWorkerUnavailable:
            with _PROCESS_LOCK:
                interrupted = generation != _GENERATION
            if interrupted:
                raise RuntimeError("Phonon synthesis was interrupted.")
            raise
        finally:
            with _PROCESS_LOCK:
                _WORKER_BUSY = False


def _cli_synth(text: str, output: Path, directory: Path, voice: str) -> Path:
    output.unlink(missing_ok=True)
    command = [
        _exe(), "--model", str(directory), "--voice", voice,
        "--quant", os.environ.get("JARVIS_PHONON_QUANT", "q8").strip() or "q8",
        "--lang", "en",
    ]
    threads = os.environ.get("JARVIS_PHONON_THREADS", "").strip()
    if threads.isdigit() and int(threads) > 0:
        command += ["--threads", str(int(threads))]
    command += [text, "-o", str(output)]

    global _ACTIVE_PROCESS
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
            _ACTIVE_PROCESS = process
        try:
            stdout, stderr = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
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
    voice = _selected_voice(directory)
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

    try:
        try:
            return _request_worker(text, output)
        except PersistentWorkerUnavailable as exc:
            # Keep existing Termux installs working if the optional pyo3 package
            # cannot build or import; this fallback has the old per-chunk startup cost.
            print(f"[PHONON] Persistent worker unavailable; using ptts CLI: {exc}", file=sys.stderr, flush=True)
            return _cli_synth(text, output, directory, voice)
    except Exception:
        output.unlink(missing_ok=True)
        raise


def interrupt() -> None:
    """Interrupt active synthesis; keep an idle preloaded worker alive."""
    global _GENERATION
    with _PROCESS_LOCK:
        _GENERATION += 1
        process = _ACTIVE_PROCESS
        worker = _WORKER_PROCESS if _WORKER_BUSY else None
    for active in (process, worker):
        if active is not None and active.poll() is None:
            try:
                active.terminate()
            except OSError:
                pass
