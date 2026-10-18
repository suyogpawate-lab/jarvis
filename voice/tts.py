#!/usr/bin/env python3
"""Minimal JARVIS TTS engine using Edge TTS and mpv."""

import asyncio
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import edge_tts

VOICE = "en-GB-RyanNeural"
PITCH = "-20Hz"
RATE = "-6%"


# Playback activity tracking, so a UI can show "speaking" for exactly as long
# as audio is being generated/played (covers speak() and speak_async()).
_active = 0
_lock = threading.Lock()


def _enter() -> None:
    global _active
    with _lock:
        _active += 1


def _exit() -> None:
    global _active
    with _lock:
        _active = max(0, _active - 1)


def is_speaking() -> bool:
    """True while any speech is being synthesized or played."""
    return _active > 0


def prepare_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()

    # Remove comma before direct address "sir".
    text = re.sub(r",\s*(sir)\b", r" \1", text, flags=re.IGNORECASE)

    # Replace all full stops except a final full stop with commas.
    if text.endswith("."):
        text = text[:-1].replace(".", ",") + "."
    else:
        text = text.replace(".", ",")

    # Normalize punctuation spacing.
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])(?=[^\s])", lambda m: m.group(0) + " ", text)

    return text.strip()


async def _synthesize(text: str, output: Path) -> None:
    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate=RATE,
        pitch=PITCH,
    )
    await communicate.save(str(output))


def speak(text: str, wait: bool = True) -> bool:
    """Speak text through mpv. Returns True on successful playback."""
    text = prepare_text(text)
    if not text:
        return False

    if not shutil.which("mpv"):
        raise RuntimeError("mpv is not installed or is not on PATH.")
    if not shutil.which("edge-tts"):
        raise RuntimeError("edge-tts is not installed or is not on PATH.")

    _enter()
    try:
        with tempfile.TemporaryDirectory(prefix="jarvis_tts_") as temp_dir:
            audio = Path(temp_dir) / "speech.mp3"
            asyncio.run(_synthesize(text, audio))

            result = subprocess.run(
                [
                    "mpv",
                    "--no-video",
                    "--really-quiet",
                    "--",
                    str(audio),
                ],
                check=False,
            )
            return result.returncode == 0
    finally:
        _exit()


def speak_async(text: str) -> subprocess.Popen:
    """Generate audio and launch mpv asynchronously."""
    # Kept separate from speak() so callers can explicitly request blocking
    # playback or manage their own background playback process.
    text = prepare_text(text)
    if not text:
        raise ValueError("Text is empty.")

    if not shutil.which("mpv"):
        raise RuntimeError("mpv is not installed or is not on PATH.")

    _enter()
    temp_dir = tempfile.mkdtemp(prefix="jarvis_tts_")
    try:
        audio = Path(temp_dir) / "speech.mp3"
        asyncio.run(_synthesize(text, audio))
        proc = subprocess.Popen(
            ["mpv", "--no-video", "--really-quiet", "--", str(audio)]
        )
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _exit()
        raise

    def _reap() -> None:
        try:
            proc.wait()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            _exit()

    threading.Thread(target=_reap, daemon=True).start()
    return proc


if __name__ == "__main__":
    speak(
        "Good morning sir, I've completed the system analysis, "
        "all systems are ready."
    )
