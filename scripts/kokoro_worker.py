#!/usr/bin/env python3
"""Persistent Kokoro ONNX worker with a selected stock voice and matching LPC whisper."""
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
    "h": "hi", "i": "it", "j": "ja", "p": "pt-br", "z": "cmn",
}
EXPECTED_V1_VOICES = 54
EXPECTED_V11_VOICES = 103
WHISPER_VOICE = "jarvis_whisper"


def apply_lpc_whisper(audio: np.ndarray, breath_mix: float = 0.82) -> np.ndarray:
    """Create an unvoiced whisper texture while retaining the selected voice's formants."""
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
    magnitude = np.abs(np.fft.rfft(frames, axis=1)) + 1e-7
    cepstrum = np.fft.irfft(np.log(magnitude), axis=1)
    lifter_cutoff = 28
    cepstrum[:, lifter_cutoff:-lifter_cutoff] = 0.0
    envelope = np.exp(np.fft.rfft(cepstrum, axis=1).real)

    rng = np.random.default_rng()
    noise = rng.standard_normal(len(padded)).astype(np.float32)
    noise[1:] -= 0.65 * noise[:-1]
    noise_frames = np.lib.stride_tricks.as_strided(
        noise, shape=(n_frames, n_fft),
        strides=(noise.strides[0] * hop, noise.strides[0]),
    ) * win
    phase = np.angle(np.fft.rfft(noise_frames, axis=1))
    whisper_frames = np.fft.irfft(envelope * np.exp(1j * phase), axis=1) * win

    output = np.zeros(len(padded), dtype=np.float32)
    window_sum = np.zeros(len(padded), dtype=np.float32)
    win_sq = win ** 2
    for index in range(n_frames):
        start = index * hop
        output[start:start + n_fft] += whisper_frames[index]
        window_sum[start:start + n_fft] += win_sq
    output /= np.maximum(window_sum, 1e-6)
    whisper = output[pad_len:pad_len + len(audio)]
    whisper = whisper / (np.max(np.abs(whisper)) + 1e-6) * np.max(np.abs(audio))
    mix = max(0.0, min(1.0, float(breath_mix)))
    return ((mix * whisper) + ((1.0 - mix) * audio * 0.5)).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    samples = np.nan_to_num(np.asarray(audio, dtype=np.float32).reshape(-1))
    pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())


class PersistentKokoroEngine:
    """Loads only the selected voice's matching model; caches normal and whisper styles."""

    def __init__(
        self,
        model_v1_path: Path,
        voices_v1_path: Path,
        model_v11_path: Path,
        voices_v11_path: Path,
        selected_voice: str,
    ):
        self.model_paths = {"v1.0": model_v1_path, "v1.1-zh": model_v11_path}
        self.voice_paths = {"v1.0": voices_v1_path, "v1.1-zh": voices_v11_path}
        self.threads = max(1, min(4, int(os.environ.get("JARVIS_KOKORO_THREADS", "2"))))
        self.sample_rate = SAMPLE_RATE
        self._g2p = None
        self._g2p_lang = None
        self.voice_catalog: dict[str, str] = {}

        self._scan_voice_catalog()
        if selected_voice not in self.voice_catalog:
            raise ValueError(
                f"Selected Kokoro voice {selected_voice!r} is not in the installed 157-voice catalog."
            )
        self.selected_voice = selected_voice
        self.model_family = self.voice_catalog[selected_voice]
        self.model_path = self.model_paths[self.model_family]
        self.voices_path = self.voice_paths[self.model_family]
        self._init_session(self.model_path)
        self.selected_lang = self._language_for_voice(selected_voice)
        self.base_style = self._load_voice_style(selected_voice)
        # Both variants are resident from startup. Whisper uses the same speaker
        # embedding and applies the supplied LPC/formant-preserving whisper DSP.
        self.whisper_style = self.base_style.copy()

    @staticmethod
    def _archive_names(path: Path) -> list[str]:
        if not path.is_file():
            raise FileNotFoundError(f"Kokoro voice archive is missing: {path}")
        try:
            with np.load(str(path), allow_pickle=False) as archive:
                return list(archive.files)
        except Exception as exc:
            raise RuntimeError(f"Cannot read Kokoro voice archive {path.name}: {exc}") from exc

    def _scan_voice_catalog(self) -> None:
        v1_names = self._archive_names(self.voice_paths["v1.0"])
        v11_names = self._archive_names(self.voice_paths["v1.1-zh"])
        if len(v1_names) != EXPECTED_V1_VOICES:
            raise RuntimeError(
                f"Kokoro v1.0 archive must contain {EXPECTED_V1_VOICES} voices; found {len(v1_names)}."
            )
        if len(v11_names) != EXPECTED_V11_VOICES:
            raise RuntimeError(
                f"Kokoro v1.1-zh archive must contain {EXPECTED_V11_VOICES} voices; found {len(v11_names)}."
            )
        overlap = set(v1_names).intersection(v11_names)
        if overlap:
            raise RuntimeError(f"Kokoro voice IDs overlap between model packs: {sorted(overlap)}")
        self.voice_catalog = {
            **{name: "v1.0" for name in v1_names},
            **{name: "v1.1-zh" for name in v11_names},
        }
        if len(self.voice_catalog) != 157:
            raise RuntimeError(f"Expected 157 unique Kokoro voices; found {len(self.voice_catalog)}.")

    @staticmethod
    def _language_for_voice(voice: str) -> str:
        prefix = voice[:1].lower()
        if prefix not in LANGS:
            raise ValueError(f"Unsupported Kokoro language prefix in voice ID {voice!r}.")
        return LANGS[prefix]

    def _load_voice_style(self, name: str) -> np.ndarray:
        family = self.voice_catalog[name]
        archive_path = self.voice_paths[family]
        with np.load(str(archive_path), allow_pickle=False) as archive:
            style = np.array(archive[name], dtype=np.float32, copy=True)
        if style.ndim != 3 or style.shape[0] < 2:
            raise RuntimeError(f"Unexpected style embedding shape for {name}: {style.shape}")
        return style

    def _init_session(self, model_path: Path) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"Kokoro model is missing: {model_path}")
        options = ort.SessionOptions()
        options.intra_op_num_threads = self.threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        started = time.monotonic()
        self.session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        metadata = self.session.get_modelmeta().custom_metadata_map
        config = metadata.get("kokoro_config")
        if not config:
            raise RuntimeError(f"{model_path.name} is missing embedded kokoro_config vocabulary metadata.")
        self.vocab = json.loads(config)["vocab"]
        self.input_types = {
            item.name: DTYPES.get(item.type, np.float32)
            for item in self.session.get_inputs()
        }
        self.token_key = "input_ids" if "input_ids" in self.input_types else "tokens"
        required = {self.token_key, "style", "speed"}
        if not required.issubset(self.input_types):
            raise RuntimeError(f"Unexpected Kokoro ONNX inputs: {sorted(self.input_types)}")
        self.model_load_seconds = time.monotonic() - started

    def _phonemize(self, text: str, lang: str) -> list[tuple[str, float]]:
        if lang in ("cmn", "ja") and self._g2p_lang != lang:
            try:
                if lang == "cmn":
                    from misaki import zh
                    self._g2p = zh.ZHG2P(version=None)
                else:
                    from misaki import ja
                    self._g2p = ja.JAG2P()
                self._g2p_lang = lang
            except ImportError as exc:
                extra = "zh" if lang == "cmn" else "ja"
                raise RuntimeError(
                    f"Kokoro voice {self.selected_voice} needs Misaki G2P; install with: "
                    f"python -m pip install 'misaki[{extra}]' ({exc})"
                ) from exc

        text = text.replace("--", "—")
        parts = re.split(r"([.,!?;:—。！？；：，、]+)", text)
        clauses = []
        for index in range(0, len(parts), 2):
            phrase = parts[index].strip()
            if not phrase:
                continue
            punct = parts[index + 1].strip() if index + 1 < len(parts) else "."
            mark = punct[0] if punct else "."
            if lang in ("cmn", "ja"):
                phonemes, _ = self._g2p(phrase)
                ipa = " ".join(str(phonemes).split())
            else:
                result = subprocess.run(
                    ["espeak-ng", "-q", "--ipa", "-v", lang, phrase],
                    capture_output=True, text=True, timeout=20,
                )
                if result.returncode:
                    raise RuntimeError(
                        f"espeak-ng phonemization failed for language {lang}: {result.stderr.strip()}"
                    )
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

    def warmup(self) -> None:
        sample = "你好。" if self.selected_lang == "cmn" else (
            "こんにちは。" if self.selected_lang == "ja" else "Ready."
        )
        clauses = self._phonemize(sample, self.selected_lang)
        if not clauses:
            raise RuntimeError(f"Kokoro G2P warmup returned no phonemes for {self.selected_voice}.")
        tokens = [self.vocab[p] for p in clauses[0][0] if p in self.vocab][:510]
        if not tokens:
            raise RuntimeError(f"Kokoro G2P output contains no model vocabulary symbols for {self.selected_voice}.")
        audio = self._infer(tokens, self.base_style, 1.0)
        # Exercise the whisper path at startup too; no second model or download is needed.
        apply_lpc_whisper(audio)

    def _voice_style(self, voice: str) -> tuple[np.ndarray, str, str]:
        if voice in ("", "default", self.selected_voice):
            return self.base_style, self.selected_lang, "normal"
        if voice == WHISPER_VOICE:
            return self.whisper_style, self.selected_lang, "whisper"
        raise ValueError(
            f"Only the selected Kokoro voice {self.selected_voice!r} is preloaded; "
            "choose another voice in setup and restart JARVIS."
        )

    def synthesize(self, text: str, voice: str, speed: float, output: Path) -> dict:
        style, lang, mode = self._voice_style(voice)
        speed = max(0.5, min(2.0, float(speed)))
        clauses = self._phonemize(text, lang)
        segments = []
        for index, (phonemes, pause) in enumerate(clauses):
            tokens = [self.vocab[p] for p in phonemes if p in self.vocab][:510]
            if tokens:
                segments.append(self._infer(tokens, style, speed))
                if index < len(clauses) - 1 and pause > 0:
                    segments.append(np.zeros(int(pause * SAMPLE_RATE), dtype=np.float32))
        if not segments:
            raise RuntimeError("Kokoro produced no phoneme tokens for this text.")
        audio = np.concatenate(segments).astype(np.float32)
        if mode == "whisper":
            breath_mix = float(os.environ.get("JARVIS_KOKORO_BREATH_MIX", "0.82"))
            audio = apply_lpc_whisper(audio, breath_mix)
        write_wav(output, audio)
        return {
            "samples": int(len(audio)),
            "sample_rate": SAMPLE_RATE,
            "mode": mode,
            "voice": self.selected_voice,
            "model_family": self.model_family,
        }


def main() -> int:
    if len(sys.argv) != 6:
        raise SystemExit(
            "usage: kokoro_worker.py MODEL_V1.onnx VOICES_V1.bin MODEL_V11_ZH.onnx "
            "VOICES_V11_ZH.bin SELECTED_VOICE"
        )
    engine = PersistentKokoroEngine(
        Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5]
    )
    engine.warmup()
    print(json.dumps({
        "ready": True,
        "model": "Kokoro-82M",
        "model_family": engine.model_family,
        "model_path": str(engine.model_path),
        "voices_loaded": len(engine.voice_catalog),
        "selected_voice": engine.selected_voice,
        "normal_style_preloaded": True,
        "whisper_style_preloaded": True,
        "model_load_seconds": round(engine.model_load_seconds, 3),
        "sample_rate": SAMPLE_RATE,
    }), flush=True)

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            text = " ".join(str(request.get("text", "")).split())
            voice = str(request.get("voice", engine.selected_voice))
            speed = float(request.get("speed", 1.0))
            output = Path(request["output"])
            if not text:
                raise ValueError("Text is empty.")
            output.parent.mkdir(parents=True, exist_ok=True)
            info = engine.synthesize(text, voice, speed, output)
            print(json.dumps({"ok": True, **info}), flush=True)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
