#!/usr/bin/env python3
"""Persistent FP16 Kokoro ONNX worker with the user's male-whisper DSP."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort

SAMPLE_RATE = 24000
PAUSE_MAP = {".": 0.32, "!": 0.32, "?": 0.34, ";": 0.22, ":": 0.20, "—": 0.20, "-": 0.14, ",": 0.14}
DTYPES = {
    "tensor(float16)": np.float16, "tensor(float)": np.float32,
    "tensor(double)": np.float64, "tensor(int64)": np.int64,
    "tensor(int32)": np.int32,
}
LANGS = {
    "a": "en-us", "b": "en-gb", "e": "es", "f": "fr-fr",
    "h": "hi", "i": "it", "j": "ja", "p": "pt-br", "z": "zh",
}


def apply_lpc_whisper(audio: np.ndarray, breath_mix: float = 0.82) -> np.ndarray:
    """Cepstral vocal-tract envelope + aspirated noise whisper vocoder."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(audio) < 64:
        return audio
    n_fft, hop = 1024, 256
    win = np.hanning(n_fft).astype(np.float32)
    pad_len = n_fft // 2
    padded = np.pad(audio, (pad_len, pad_len), mode="reflect")
    n_frames = 1 + (len(padded) - n_fft) // hop
    frames = np.lib.stride_tricks.as_strided(
        padded, shape=(n_frames, n_fft),
        strides=(padded.strides[0] * hop, padded.strides[0]),
    ) * win
    mag = np.abs(np.fft.rfft(frames, axis=1)) + 1e-7
    cepstrum = np.fft.irfft(np.log(mag), axis=1)
    lifter_cutoff = 28
    cepstrum[:, lifter_cutoff:-lifter_cutoff] = 0.0
    formant_env = np.exp(np.fft.rfft(cepstrum, axis=1).real)
    rng = np.random.default_rng()
    noise = rng.standard_normal(len(padded)).astype(np.float32)
    noise[1:] -= 0.65 * noise[:-1]
    noise_frames = np.lib.stride_tricks.as_strided(
        noise, shape=(n_frames, n_fft),
        strides=(noise.strides[0] * hop, noise.strides[0]),
    ) * win
    noise_phase = np.angle(np.fft.rfft(noise_frames, axis=1))
    whisper_spec = formant_env * np.exp(1j * noise_phase)
    whisper_frames = np.fft.irfft(whisper_spec, axis=1) * win
    out = np.zeros(len(padded), dtype=np.float32)
    win_sum = np.zeros(len(padded), dtype=np.float32)
    win_sq = win ** 2
    for index in range(n_frames):
        start = index * hop
        out[start:start + n_fft] += whisper_frames[index]
        win_sum[start:start + n_fft] += win_sq
    out /= np.maximum(win_sum, 1e-6)
    whisper = out[pad_len:pad_len + len(audio)]
    whisper = whisper / (np.max(np.abs(whisper)) + 1e-6) * np.max(np.abs(audio))
    return ((breath_mix * whisper) + ((1.0 - breath_mix) * audio * 0.5)).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    samples = np.nan_to_num(np.asarray(audio, dtype=np.float32).reshape(-1))
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = np.rint(pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())


class PersistentKokoroEngine:
    def __init__(self, model_path: Path, voices_path: Path):
        threads = max(1, min(4, int(os.environ.get("JARVIS_KOKORO_THREADS", "2"))))
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.enable_cpu_mem_arena = True
        options.enable_mem_pattern = True
        started = time.monotonic()
        self.session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        metadata = self.session.get_modelmeta().custom_metadata_map
        config = metadata.get("kokoro_config")
        if not config:
            raise RuntimeError("FP16 Kokoro model is missing embedded kokoro_config vocabulary metadata.")
        self.vocab = json.loads(config)["vocab"]
        self.voices = np.load(str(voices_path), allow_pickle=False)
        self.input_types = {item.name: DTYPES.get(item.type, np.float32) for item in self.session.get_inputs()}
        self.token_key = "input_ids" if "input_ids" in self.input_types else "tokens"
        required = {self.token_key, "style", "speed"}
        if not required.issubset(self.input_types):
            raise RuntimeError(f"Unexpected Kokoro ONNX inputs: {sorted(self.input_types)}")
        self.output_names = [item.name for item in self.session.get_outputs()]
        if not self.output_names:
            raise RuntimeError("Kokoro ONNX model has no outputs.")
        self.voice_names = sorted(self.voices.files)
        if len(self.voice_names) < 54:
            raise RuntimeError(f"Expected all 54 stock voices; voice archive contains {len(self.voice_names)}.")
        self.model_load_seconds = time.monotonic() - started

    def _voice_style(self, voice: str) -> tuple[np.ndarray, str, str]:
        if voice == "jarvis_whisper":
            mode = os.environ.get("JARVIS_KOKORO_MODE", "formant").strip().lower()
            if mode not in ("formant", "lpc"):
                raise ValueError("JARVIS_KOKORO_MODE must be formant or lpc.")
            male = os.environ.get("JARVIS_KOKORO_MALE_VOICE", "am_eric").strip()
            if male not in self.voice_names or not male.startswith(("am_", "bm_")):
                raise ValueError("JARVIS_KOKORO_MALE_VOICE must be an American or British male voice ID.")
            nicole = self.voices["af_nicole"].astype(np.float32)
            male_style = self.voices[male].astype(np.float32)
            if mode == "formant":
                style = 0.90 * nicole + 0.10 * male_style
            else:
                style = 0.75 * male_style + 0.25 * nicole
            return style, ("en-gb" if male.startswith("bm_") else "en-us"), mode
        if voice not in self.voice_names:
            raise ValueError(f"Unknown Kokoro voice {voice!r}.")
        lang = LANGS.get(voice[0], "en-us")
        return self.voices[voice].astype(np.float32), lang, "stock"

    def _phonemize(self, text: str, lang: str) -> list[tuple[str, float]]:
        text = text.replace("--", "—")
        parts = re.split(r"([.,!?;:—]+)", text)
        clauses = []
        for index in range(0, len(parts), 2):
            phrase = parts[index].strip()
            if not phrase:
                continue
            punct = parts[index + 1].strip() if index + 1 < len(parts) else "."
            mark = punct[0] if punct else "."
            result = subprocess.run(
                ["espeak-ng", "-q", "--ipa", "-v", lang, phrase],
                capture_output=True, text=True, timeout=20,
            )
            if result.returncode:
                raise RuntimeError(f"espeak-ng phonemization failed for language {lang}: {result.stderr.strip()}")
            ipa = " ".join(result.stdout.strip().split())
            if ipa:
                if mark in self.vocab:
                    ipa += mark
                clauses.append((ipa, PAUSE_MAP.get(mark, 0.20)))
        return clauses

    def _trim(self, audio: np.ndarray, threshold: float = 0.008) -> np.ndarray:
        mask = np.abs(audio) > threshold
        if not np.any(mask):
            return audio
        start = max(0, int(np.argmax(mask)) - int(0.02 * SAMPLE_RATE))
        end = min(len(audio), len(audio) - int(np.argmax(mask[::-1])) + int(0.03 * SAMPLE_RATE))
        return audio[start:end]

    def _infer(self, tokens: list[int], voice_style: np.ndarray, speed: float) -> np.ndarray:
        if not tokens:
            return np.zeros(0, dtype=np.float32)
        row = voice_style[min(len(tokens), len(voice_style)) - 1]
        inputs = {
            self.token_key: np.asarray([[0, *tokens, 0]], dtype=self.input_types[self.token_key]),
            "style": np.asarray(row, dtype=self.input_types["style"]),
            "speed": np.asarray([speed], dtype=self.input_types["speed"]),
        }
        return self._trim(np.asarray(self.session.run(None, inputs)[0]).squeeze().astype(np.float32))

    def synthesize(self, text: str, voice: str, speed: float, output: Path) -> dict:
        style, lang, mode = self._voice_style(voice)
        speed = max(0.5, min(2.0, float(speed)))
        synth_speed = speed * 1.12 if mode == "formant" else speed
        clauses = self._phonemize(text, lang)
        segments = []
        for index, (ipa, pause) in enumerate(clauses):
            tokens = [self.vocab[p] for p in ipa if p in self.vocab][:510]
            if tokens:
                segments.append(self._infer(tokens, style, synth_speed))
                if index < len(clauses) - 1 and pause > 0:
                    segments.append(np.zeros(int(pause * SAMPLE_RATE), dtype=np.float32))
        if not segments:
            raise RuntimeError("Kokoro produced no phoneme tokens for this text.")
        audio = np.concatenate(segments).astype(np.float32)
        if mode == "lpc":
            breath_mix = float(os.environ.get("JARVIS_KOKORO_BREATH_MIX", "0.82"))
            audio = apply_lpc_whisper(audio, max(0.0, min(1.0, breath_mix)))
        write_wav(output, audio)
        if mode == "formant":
            depth = float(os.environ.get("JARVIS_KOKORO_FORMANT_DEPTH", "-300"))
            ratio = 2.0 ** (depth / 1200.0)
            tempo = 1.0 / ratio
            sox = os.environ.get("JARVIS_SOX_BIN", "sox")
            raw = output.with_suffix(".raw.wav")
            output.replace(raw)
            try:
                subprocess.run(
                    [sox, str(raw), str(output), "speed", f"{ratio:.5f}",
                     "tempo", "-s", f"{tempo:.5f}", "bass", "+4", "treble", "-3"],
                    check=True, capture_output=True, timeout=120,
                )
            except Exception:
                raw.replace(output)
                raise
            finally:
                raw.unlink(missing_ok=True)
        return {"samples": int(len(audio)), "sample_rate": SAMPLE_RATE, "mode": mode}

    def warmup(self) -> None:
        # Run the real inference path once so first user speech avoids model setup.
        self.synthesize("Ready.", "jarvis_whisper", 1.0, Path(os.devnull) if False else Path("/dev/null.wav"))


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: kokoro_worker.py MODEL.onnx VOICES.bin")
    engine = PersistentKokoroEngine(Path(sys.argv[1]), Path(sys.argv[2]))
    # Warm-up inference without writing a persistent file.
    style, lang, mode = engine._voice_style("jarvis_whisper")
    clauses = engine._phonemize("Ready.", lang)
    for ipa, _ in clauses:
        tokens = [engine.vocab[p] for p in ipa if p in engine.vocab][:510]
        if tokens:
            engine._infer(tokens, style, 1.12 if mode == "formant" else 1.0)
    print(json.dumps({
        "ready": True, "model": "Kokoro-82M-v1.0-FP16",
        "voices_loaded": len(engine.voice_names), "voices": engine.voice_names,
        "model_load_seconds": round(engine.model_load_seconds, 3),
        "sample_rate": SAMPLE_RATE,
    }), flush=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            text = " ".join(str(request.get("text", "")).split())
            voice = str(request.get("voice", "jarvis_whisper"))
            speed = float(request.get("speed", 1.0))
            output = Path(request["output"])
            if not text:
                raise ValueError("Text is empty.")
            if not output.parent.exists():
                output.parent.mkdir(parents=True, exist_ok=True)
            info = engine.synthesize(text, voice, speed, output)
            print(json.dumps({"ok": True, **info}), flush=True)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
