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


# Interrupt support: the current mpv process and a generation counter, so
# speech that is still being synthesized when interrupt() is called is dropped.
_proc = None
_generation = 0


def interrupt() -> None:
    """Stop whatever is being spoken right now (and any synthesis in flight)."""
    global _generation, _proc
    with _lock:
        _generation += 1
        proc = _proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def is_speaking() -> bool:
    """True while any speech is being synthesized or played."""
    return _active > 0

def play_recorded(audio_path: str | Path) -> bool:
    """Play a prerecorded MP3 through mpv while marking voice output as active."""
    global _proc
    audio = Path(audio_path)
    if not audio.is_file():
        return False
    if not shutil.which("mpv"):
        raise RuntimeError("mpv is not installed or is not on PATH.")

    with _lock:
        my_generation = _generation

    _enter()
    try:
        with _lock:
            if _generation != my_generation:
                return True
            proc = subprocess.Popen(
                ["mpv", "--no-video", "--no-terminal", "--really-quiet", "--", str(audio)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _proc = proc

        returncode = proc.wait()
        with _lock:
            if _proc is proc:
                _proc = None
            interrupted = _generation != my_generation
        return interrupted or returncode == 0
    finally:
        _exit()


def strip_markdown(text: str) -> str:
    """Remove markdown symbols so TTS never reads them aloud."""
    text = str(text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)         # code blocks
    text = re.sub(r"`([^`]*)`", r"\1", text)                        # inline code
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)           # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)            # links -> label
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)               # headings
    text = re.sub(r"(?m)^\s*[-*+\u2022]\s+", "", text)              # bullets
    text = re.sub(r"(?m)^\s*>\s?", "", text)                        # quotes
    text = re.sub(r"(\*{1,3}|_{2,3}|~{2})(?=\S)(.+?)(?<=\S)\1", r"\2", text)  # bold/italic
    text = re.sub(r"[*#~`|^]", "", text)                             # leftovers
    text = re.sub(r"(?<!\w)_|_(?!\w)", "", text)                    # stray underscores
    return text


def prepare_text(text: str) -> str:
    text = strip_markdown(text)
    text = re.sub(r"\s+", " ", text).strip()

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

    global _proc
    with _lock:
        my_generation = _generation

    _enter()
    try:
        with tempfile.TemporaryDirectory(prefix="jarvis_tts_") as temp_dir:
            audio = Path(temp_dir) / "speech.mp3"
            asyncio.run(_synthesize(text, audio))

            # Interrupted while synthesizing: drop it silently.
            with _lock:
                if _generation != my_generation:
                    return True
                proc = subprocess.Popen(
                    [
                        "mpv",
                        "--no-video",
                        "--no-terminal",
                        "--really-quiet",
                        "--",
                        str(audio),
                    ],
                    # mpv must not read the terminal, or it swallows keystrokes.
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                _proc = proc

            returncode = proc.wait()
            with _lock:
                if _proc is proc:
                    _proc = None
                interrupted = _generation != my_generation
            return interrupted or returncode == 0
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
