#!/usr/bin/env python3
"""Pre-render ten wake acknowledgements with the currently selected JARVIS voice."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis_env import load_env
load_env()

from voice.wake_responses import PHRASES, audio_dir, selected_voice_key


def _synthesize_local(provider: str, phrase: str, target: Path) -> None:
    if provider == "kokoro":
        from voice.kokoro_tts import synth, warmup
        warmup()
        generated = synth(phrase)
    elif provider == "piper":
        from voice.piper_tts import _synthesize_to_wav
        generated = _synthesize_to_wav(phrase)
    elif provider == "phonon":
        from voice.phonon_tts import synth, warmup
        warmup()
        generated = synth(phrase)
    elif provider in ("say", "sherpa"):
        import soundfile as sf
        from voice.sherpa_tts import _engine, _paths
        voice = os.environ.get("JARVIS_SHERPA_VOICE", "alan").strip().lower()
        voice = voice if voice in ("alan", "bryce") else "alan"
        engine = _engine(voice)
        audio = engine.generate(phrase, sid=0, speed=1.0)
        if audio.samples is None or len(audio.samples) == 0:
            raise RuntimeError("Sherpa returned empty wake audio.")
        target.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(target), audio.samples, audio.sample_rate)
        return
    else:
        raise RuntimeError(f"Unsupported local wake voice provider: {provider}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if generated.resolve() != target.resolve():
        target.write_bytes(generated.read_bytes())
        generated.unlink(missing_ok=True)


async def _synthesize_edge(phrase: str, target: Path) -> None:
    from voice.tts import _synthesize
    await _synthesize(phrase, target)


def main() -> int:
    provider = os.environ.get("JARVIS_TTS_PROVIDER", "edge").strip().lower() or "edge"
    directory = audio_dir()
    directory.mkdir(parents=True, exist_ok=True)
    print(f"Preparing 10 wake greetings: {selected_voice_key()}")
    for index, phrase in enumerate(PHRASES, 1):
        suffix = ".mp3" if provider == "edge" else ".wav"
        target = directory / f"wake_{index:02d}{suffix}"
        if target.is_file() and target.stat().st_size > 1024:
            print(f"[{index:02d}/10] Cached: {target.name}")
            continue
        if provider == "edge":
            asyncio.run(_synthesize_edge(phrase, target))
        else:
            _synthesize_local(provider, phrase, target)
        if not target.is_file() or target.stat().st_size <= 1024:
            raise RuntimeError(f"Failed to create valid wake clip {target.name}")
        print(f"[{index:02d}/10] Generated: {phrase}")
    print(f"All 10 wake greetings are ready in {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
