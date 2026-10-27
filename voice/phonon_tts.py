"""Phonon TTS via the Rust `ptts` binary (offline, local model): synth(text) -> wav Path.

Setup (Termux): model folder ~/phonon-model (config.json, tokenizer.json, model.q8.gguf,
default-voice.safetensors, voices/*.safetensors). Searched in $JARVIS_PHONON_DIR,
~/phonon-model, ~/jarvis/models/phonon.
.env options: JARVIS_PHONON_VOICE (default edwin; also hugh, spencer, toby, aldric,
trevor, bramwell, default), JARVIS_PHONON_QUANT (q8), JARVIS_PHONON_THREADS (optional).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def model_dir():
    cands = [os.environ.get("JARVIS_PHONON_DIR", "").strip(),
             Path.home() / "phonon-model", ROOT / "models" / "phonon",
             ROOT / "models" / "phonon" / "phonon-model"]
    for c in cands:
        if c and (Path(c) / "model.q8.gguf").is_file():
            return Path(c)
    raise RuntimeError("Phonon model folder not found; expected ~/phonon-model (set JARVIS_PHONON_DIR to change).")


def _exe():
    exe = shutil.which("ptts") or str(Path.home() / ".cargo" / "bin" / "ptts")
    if not Path(exe).is_file():
        raise RuntimeError("ptts not found; install with: cargo install ptts --locked --features cli")
    return exe


def synth(text):
    text = " ".join(str(text or "").split())
    if not text:
        raise RuntimeError("Phonon received empty text.")
    d = model_dir()
    voice = os.environ.get("JARVIS_PHONON_VOICE", "").strip().lower() or "edwin"
    if voice != "default" and not (d / "voices" / f"{voice}.safetensors").is_file():
        voice = "default"
    # Termux has no /tmp; keep output inside the project cache.
    out_dir = ROOT / "cache" / "phonon"
    out_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="speech-", suffix=".wav", dir=str(out_dir))
    os.close(fd)
    os.unlink(name)  # ptts creates the file itself
    argv = [_exe(), "--model", str(d), "--voice", voice,
            "--quant", os.environ.get("JARVIS_PHONON_QUANT", "q8").strip() or "q8", "--lang", "en"]
    threads = os.environ.get("JARVIS_PHONON_THREADS", "").strip()
    if threads.isdigit():
        argv += ["--threads", threads]
    argv += ["-o", name, "--", text]
    r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
    p = Path(name)
    if r.returncode or not p.is_file() or p.stat().st_size == 0:
        p.unlink(missing_ok=True)
        raise RuntimeError(f"ptts failed: {(r.stderr or r.stdout).strip()[-200:]}")
    return p
