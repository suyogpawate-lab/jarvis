#!/usr/bin/env python3
"""Benchmark Kokoro startup, phonemization, inference and end-to-end synthesis.

Run once per execution provider in separate processes:
  JARVIS_KOKORO_EP=cpu python scripts/benchmark_kokoro_latency.py
  JARVIS_KOKORO_EP=xnnpack python scripts/benchmark_kokoro_latency.py
  JARVIS_KOKORO_EP=nnapi python scripts/benchmark_kokoro_latency.py
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.kokoro_worker import PersistentKokoroEngine
MODEL_DIR = ROOT / "models" / "kokoro82m"
VOICE = os.environ.get("JARVIS_KOKORO_NORMAL_VOICE", "am_eric").strip() or "am_eric"
TEXT = "Hello. This is a Kokoro latency benchmark. I am measuring phonemization, neural inference, and total audio generation time."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=4, help="steady-state synthesis repetitions")
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("--runs must be at least 2")

    started = time.perf_counter()
    engine = PersistentKokoroEngine(
        MODEL_DIR / "kokoro-v1.0.fp16.onnx",
        MODEL_DIR / "voices-v1.0.bin",
        MODEL_DIR / "kokoro-v1.1-zh.fp16.onnx",
        MODEL_DIR / "voices-v1.1-zh.bin",
        VOICE,
    )
    constructed = time.perf_counter()
    engine.warmup()
    warmed = time.perf_counter()

    g2p_start = time.perf_counter()
    clauses = engine._phonemize(TEXT, engine.selected_lang)
    g2p_seconds = time.perf_counter() - g2p_start
    tokens_by_clause = [
        [engine.vocab[p] for p in phonemes if p in engine.vocab][:510]
        for phonemes, _ in clauses
    ]

    inference_start = time.perf_counter()
    audio_samples = 0
    for tokens in tokens_by_clause:
        if tokens:
            audio_samples += len(engine._infer(tokens, engine.base_style, 1.0))
    inference_seconds = time.perf_counter() - inference_start

    full_runs = []
    audio_seconds = 0.0
    for _ in range(args.runs):
        with tempfile.NamedTemporaryFile(prefix="kokoro-bench-", suffix=".wav", delete=False) as tmp:
            output = Path(tmp.name)
        try:
            run_start = time.perf_counter()
            info = engine.synthesize(TEXT, VOICE, 1.0, output)
            elapsed = time.perf_counter() - run_start
            full_runs.append(elapsed)
            audio_seconds = info["samples"] / info["sample_rate"]
        finally:
            output.unlink(missing_ok=True)

    print(json.dumps({
        "provider_requested": engine.requested_execution_provider,
        "providers_registered": engine.execution_providers,
        "voice": VOICE,
        "model_family": engine.model_family,
        "model_load_seconds": round(engine.model_load_seconds, 3),
        "engine_construction_seconds": round(constructed - started, 3),
        "warmup_seconds": round(warmed - constructed, 3),
        "phonemization_ms": round(g2p_seconds * 1000, 1),
        "inference_only_ms": round(inference_seconds * 1000, 1),
        "inference_audio_seconds": round(audio_samples / engine.sample_rate, 3),
        "synthesis_first_ms": round(full_runs[0] * 1000, 1),
        "synthesis_median_ms": round(statistics.median(full_runs) * 1000, 1),
        "generated_audio_seconds": round(audio_seconds, 3),
        "real_time_factor": round(audio_seconds / statistics.median(full_runs), 3),
        "runs_ms": [round(value * 1000, 1) for value in full_runs],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
