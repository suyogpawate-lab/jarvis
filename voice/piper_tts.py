"""Optional local Piper TTS backend for Termux builds exposing libpiper's C API."""
import ctypes
import os
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

from voice.tts import prepare_text

_state_lock = threading.Lock()
_synth_lock = threading.Lock()
_proc = None
_generation = 0
_synth = None
_lib = None
_runtime_lib = None


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
    home = Path.home()
    prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    return {
        "library": Path(os.environ.get("JARVIS_PIPER_LIBRARY", home / ".local/opt/piper-tts-cli/data/data/com.termux/files/usr/lib/libpiper.so")).expanduser(),
        "model": Path(os.environ.get("JARVIS_PIPER_MODEL", home / "piper_models/en_GB-alan-medium.onnx")).expanduser(),
        "config": Path(os.environ.get("JARVIS_PIPER_CONFIG", home / "piper_models/en_GB-alan-medium.onnx.json")).expanduser(),
        "espeak": Path(os.environ.get("JARVIS_ESPEAK_DATA", prefix / "share/espeak-ng-data")).expanduser(),
        "output": Path(os.environ.get("JARVIS_PIPER_OUTPUT_DIR", home / ".cache/jarvis/piper")).expanduser(),
    }


def _load():
    global _lib, _synth, _runtime_lib
    if _synth:
        return _lib, _synth
    cfg = _settings()
    for key in ("library", "model", "config"):
        if not cfg[key].is_file():
            raise RuntimeError(f"Piper {key} file not found: {cfg[key]}. Run python setup.py voice.")
    if not cfg["espeak"].is_dir():
        raise RuntimeError(f"eSpeak NG data directory not found: {cfg['espeak']}")
    try:
        # Some Termux Piper packages ship a private ONNX Runtime beside libpiper.so.
        # Load that copy first without touching $PREFIX/lib.
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
        synth = lib.piper_create(os.fsencode(cfg["model"]), os.fsencode(cfg["config"]), os.fsencode(cfg["espeak"]))
    except (OSError, AttributeError) as exc:
        raise RuntimeError(f"Could not load Piper C API from {cfg['library']}: {exc}") from exc
    if not synth:
        raise RuntimeError("Piper failed to initialize the model.")
    _lib, _synth = lib, synth
    return _lib, _synth


def interrupt():
    global _generation, _proc
    with _state_lock:
        _generation += 1
        proc = _proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


def speak(text, wait=True, speed=1.0):
    global _proc
    text = prepare_text(text)
    if not text:
        return False
    if not shutil.which("mpv"):
        raise RuntimeError("mpv is not installed or is not on PATH.")
    with _state_lock:
        generation = _generation

    # The synthesizer is single-instance, but the state lock is not held while
    # synthesizing; interrupt() can invalidate the utterance immediately.
    with _synth_lock:
        lib, synth = _load()
        cfg = _settings()
        cfg["output"].mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="speech-", suffix=".wav", dir=str(cfg["output"]))
        os.close(fd)
        audio_path = Path(name)
        try:
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
                    audio_chunks.append(ctypes.string_at(chunk.samples, int(chunk.num_samples) * ctypes.sizeof(ctypes.c_int16)))
                if chunk.is_last:
                    break
            if not audio_chunks or not sample_rate:
                raise RuntimeError("Piper returned no audio samples.")
            with wave.open(str(audio_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(b"".join(audio_chunks))

    with _state_lock:
        if _generation != generation:
            audio_path.unlink(missing_ok=True)
            return True
        command = ["mpv", "--no-video", "--no-terminal", "--really-quiet"]
        if speed and float(speed) > 0 and float(speed) != 1.0:
            command.append(f"--speed={float(speed):.3f}")
        command.extend(["--", str(audio_path)])
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _proc = proc

    if not wait:
        return proc
    try:
        code = proc.wait()
        if code == 0:
            audio_path.unlink(missing_ok=True)
            return True
        raise RuntimeError(f"mpv exited with status {code}; WAV retained at {audio_path}")
    finally:
        with _state_lock:
            if _proc is proc:
                _proc = None
