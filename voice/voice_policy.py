"""Low-cost, deterministic voice-style selection for Kokoro TTS."""
from __future__ import annotations

import os
import re

_WHISPER_CUES = re.compile(
    r"\b(?:whisper(?:ing)?|speak softly|talk softly|keep your voice down|lower your voice|"
    r"speak quietly|talk quietly|be quiet|quiet voice|hush|don't wake|do not wake|"
    r"someone is sleeping|someone's asleep|people are sleeping|in a quiet room)\b",
    re.IGNORECASE,
)
_NORMAL_CUES = re.compile(
    r"\b(?:normal voice|regular voice|usual voice|speak normally|talk normally|"
    r"stop whispering|no more whispering|don't whisper|do not whisper)\b",
    re.IGNORECASE,
)


def choose_kokoro_voice(user_prompt: str = "") -> str:
    """Return one voice ID; auto mode whispers only on clear user-side cues."""
    mode = os.environ.get("JARVIS_KOKORO_VOICE_MODE", "auto").strip().lower()
    normal = os.environ.get("JARVIS_KOKORO_NORMAL_VOICE", "").strip()
    if not normal:
        legacy = os.environ.get("JARVIS_KOKORO_VOICE", "").strip()
        normal = legacy if legacy and legacy != "jarvis_whisper" else "am_eric"
    whisper = os.environ.get("JARVIS_KOKORO_WHISPER_VOICE", "jarvis_whisper").strip()

    if mode == "normal":
        return normal
    if mode == "whisper":
        return whisper

    prompt = str(user_prompt or "").strip()
    if _NORMAL_CUES.search(prompt):
        return normal
    if mode == "auto" and _WHISPER_CUES.search(prompt):
        return whisper
    return normal
