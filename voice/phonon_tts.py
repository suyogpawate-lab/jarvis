"""Phonon TTS adapter for the local Rust `ptts` CLI.

Set JARVIS_PHONON_DIR to override the default ~/phonon-model directory.
The checkpoint and voice embeddings are installed by
scripts/prepare_phonon_assets.py; synthesis is offline after setup.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID_VOICES = {"edwin", "toby", "aldric", "trevor", "hugh", "spencer", "bramwell", "default"}
_PROCESS_LOCK = threading.Lock()
_ACTIVE_PROCESS = None
_GENERATION = 0


def interrupt() -> None:
    """Terminate an in-flight ptts synthesis so newer speech is not delayed."""
    global _GENERATION
    with _PROCESS_LOCK:
        _GENERATION += 1
        process = _ACTIVE_PROCESS
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


def synth(text: str) -> Path:
    text = " ".join(str(text or "").split())
    if not text:
        raise RuntimeError("Phonon received empty text.")

    directory = model_dir()
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

    prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    temp_dir = prefix / "tmp"
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        temp_dir = Path(tempfile.gettempdir())
    fd, filename = tempfile.mkstemp(prefix="jarvis-phonon-", suffix=".wav", dir=str(temp_dir))
    os.close(fd)
    output = Path(filename)
    output.unlink(missing_ok=True)  # ptts creates the output file itself

    command = [
        _exe(), "--model", str(directory), "--voice", voice,
        "--quant", os.environ.get("JARVIS_PHONON_QUANT", "q8").strip() or "q8",
        "--lang", "en",
    ]
    threads = os.environ.get("JARVIS_PHONON_THREADS", "").strip()
    if threads.isdigit() and int(threads) > 0:
        command += ["--threads", str(int(threads))]
    # ptts expects text as the positional argument before the -o output option.
    command += [text, "-o", str(output)]

    global _ACTIVE_PROCESS
    process = None
    try:
        # Publish the process while holding the same lock used by interrupt(),
        # so cancellation cannot race between process creation and registration.
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
