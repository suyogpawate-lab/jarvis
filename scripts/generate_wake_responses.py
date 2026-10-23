#!/usr/bin/env python3
"""Generate JARVIS's 25 wake acknowledgements once; requires internet for Edge TTS."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice.tts import _synthesize
from voice.wake_responses import AUDIO_DIR, PHRASES


async def main():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for index, phrase in enumerate(PHRASES, 1):
        target = AUDIO_DIR / f"wake_{index:02d}.mp3"
        if target.is_file() and target.stat().st_size > 1024:
            print(f"[{index:02d}/25] Already exists: {target.name}")
            continue
        await _synthesize(phrase, target)
        if not target.is_file() or target.stat().st_size <= 1024:
            raise RuntimeError(f"Audio generation failed for {target.name}")
        print(f"[{index:02d}/25] Generated: {phrase}")


if __name__ == "__main__":
    asyncio.run(main())
