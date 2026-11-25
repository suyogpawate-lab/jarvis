"""Bundled persistent KittenTTS Pico ONNX worker for JARVIS.

The worker owns one model instance for its lifetime and communicates with the
JARVIS client over a loopback-only newline-delimited JSON socket.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import socketserver

import numpy as np
import soundfile as sf
import time
import traceback
import uuid
import wave
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("JARVIS_KITTEN_PORT", "18765"))
MODEL_ID = os.environ.get("JARVIS_KITTEN_MODEL", "KittenML/kitten-tts-2-pico")
OUTPUT = Path(__file__).resolve().parents[1] / "cache" / "kitten_tts" / "worker"
OUTPUT.mkdir(parents=True, exist_ok=True)

# KittenML's English frontend uses Misaki's NLTK POS tagger. Keep its
# required corpus repository-local and explicitly visible to this worker.
NLTK_DATA = Path(__file__).resolve().parents[1] / "cache" / "nltk_data"
NLTK_DATA.mkdir(parents=True, exist_ok=True)
os.environ["NLTK_DATA"] = str(NLTK_DATA)
import nltk
if str(NLTK_DATA) not in nltk.data.path:
    nltk.data.path.insert(0, str(NLTK_DATA))
try:
    nltk.data.find("taggers/averaged_perceptron_tagger_eng", paths=[str(NLTK_DATA)])
except LookupError as exc:
    raise RuntimeError(
        "Required NLTK English POS tagger is missing. Run "
        "'bash scripts/install_kitten_tts.sh' from ~/jarvis."
    ) from exc
print(f"[Kitten] NLTK English POS tagger verified in {NLTK_DATA}", flush=True)

# Keep Hugging Face's normal cache unless the user explicitly configured one.
cache_home = os.environ.get("JARVIS_KITTEN_HOME", "").strip()
if cache_home:
    Path(cache_home).expanduser().mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(Path(cache_home).expanduser())

# JARVIS must never import code from the former sibling ~/KittenTTS checkout.
# KittenML is installed as a normal Python dependency; the worker itself and
# all JARVIS-owned files remain under ROOT.
import kittenml

package_file = Path(kittenml.__file__).resolve()
legacy_checkout = (Path.home() / "KittenTTS").resolve()
try:
    package_file.relative_to(legacy_checkout)
except ValueError:
    pass
else:
    raise RuntimeError(
        "KittenML is being imported from the external ~/KittenTTS checkout. "
        "Install the pinned KittenML package with "
        "'bash scripts/install_kitten_tts.sh' from ~/jarvis."
    )

try:
    kitten_version = importlib.metadata.version("kittenml")
except importlib.metadata.PackageNotFoundError:
    kitten_version = getattr(kittenml, "__version__", "unknown")

print(
    f"[Kitten] KittenML {kitten_version} from {package_file}",
    flush=True,
)
print(f"[Kitten] Loading {MODEL_ID} with ONNX backend...", flush=True)
from kittenml import KittenTTS
from kittenml.kittentts2_tiny import frontend as kitten_frontend
from voice.kitten_audio import KITTEN_MAX_PHONEMES, configure_frontend, synthesize_gapless

# Kitten's default frontend splits at 350 phonemes and generate() inserts
# 150 ms silence between those pieces. A 500-phoneme cap stays within the
# 510-position voice-style table, including the three special tokens.
configure_frontend(kitten_frontend, misaki_nltk=True)
print(
    f"[Kitten] Frontend chunk cap: {KITTEN_MAX_PHONEMES} phonemes; "
    "Misaki + NLTK POS tagging enabled; spaCy/PyTorch G2P disabled; "
    "inter-chunk silence disabled",
    flush=True,
)

load_started = time.perf_counter()
model = KittenTTS(MODEL_ID, backend="onnx")
# The NLTK/Misaki adapter uses the packaged pronunciation lexicon and eSpeak
# fallback; Kitten's optional BART G2P assets are not needed or downloaded.
model._g2p_dir = lambda: ""
load_seconds = time.perf_counter() - load_started
print(f"[Kitten] Model loaded in {load_seconds:.3f}s", flush=True)

print("[Kitten] Warming up ONNX inference...", flush=True)
warmup_path = OUTPUT / f".warmup-{uuid.uuid4().hex}.wav"
warmup_started = time.perf_counter()
warmup_audio, _ = synthesize_gapless(
    model, "Ready.", voice="otis", language="en", speed=0.88
)
sf.write(str(warmup_path), warmup_audio, model.sample_rate)
warmup_seconds = time.perf_counter() - warmup_started
warmup_path.unlink(missing_ok=True)
print(f"[Kitten] Warm-up completed in {warmup_seconds:.3f}s", flush=True)

_last_output: Path | None = None


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        global _last_output
        try:
            raw = self.rfile.readline(1_000_001)
            if not raw or len(raw) > 1_000_000:
                return
            request = json.loads(raw.decode("utf-8"))

            if request.get("action") == "ping":
                self.reply({
                    "ok": True,
                    "status": "ready",
                    "model": MODEL_ID,
                    "kittenml_version": kitten_version,
                    "load_seconds": load_seconds,
                    "warmup_seconds": warmup_seconds,
                })
                return

            if request.get("action") != "generate":
                self.reply({"ok": False, "error": "Unknown action"})
                return

            text = str(request.get("text") or "").strip()
            if not text:
                self.reply({"ok": False, "error": "Text cannot be empty"})
                return
            if len(text) > 20_000:
                self.reply({"ok": False, "error": "Text is too long"})
                return

            voice = str(request.get("voice") or "otis").strip()
            language = str(request.get("language") or "en").strip().lower()
            speed = float(request.get("speed", 0.88))
            if not 0.5 <= speed <= 2.0:
                self.reply({"ok": False, "error": "Speed must be between 0.5 and 2.0"})
                return

            output = OUTPUT / f"speech-{uuid.uuid4().hex}.wav"
            started = time.perf_counter()
            audio, internal_chunks = synthesize_gapless(
                model, text, voice=voice, language=language, speed=speed
            )
            if audio.size == 0:
                raise RuntimeError("KittenTTS produced no audio samples.")
            sf.write(str(output), audio, model.sample_rate)
            generation_seconds = time.perf_counter() - started

            with wave.open(str(output), "rb") as wav:
                audio_seconds = (
                    wav.getnframes() / wav.getframerate()
                    if wav.getframerate() else 0.0
                )

            previous = _last_output
            _last_output = output
            if previous and previous != output:
                previous.unlink(missing_ok=True)

            self.reply({
                "ok": True,
                "path": str(output),
                "generation_seconds": generation_seconds,
                "audio_seconds": audio_seconds,
                "rtf": generation_seconds / audio_seconds if audio_seconds else 0.0,
            })
            print(
                f"[Kitten] Generated {output.name}: {generation_seconds:.3f}s, "
                f"audio {audio_seconds:.2f}s, internal_chunks={internal_chunks}, "
                f"voice={voice}/{language}",
                flush=True,
            )
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            print(f"[Kitten ERROR] {detail}\n{traceback.format_exc()}", flush=True)
            try:
                self.reply({"ok": False, "error": detail})
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def reply(self, data):
        self.wfile.write((json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()


class Server(socketserver.TCPServer):
    allow_reuse_address = True


print(f"[Kitten] READY at {HOST}:{PORT}", flush=True)
with Server((HOST, PORT), Handler) as server:
    server.serve_forever()
