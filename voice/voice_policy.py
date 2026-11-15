"""Low-cost, deterministic voice-style selection for Kokoro TTS."""
from __future__ import annotations

import os
import re

_WHISPER_CUES = re.compile(
    r"\b(?:(?:please\s+)?(?:whisper|speak softly|talk softly|keep your voice down|lower your voice|"
    r"speak quietly|talk quietly|be quiet|hush)|(?:can|could|would) you (?:please )?"
    r"(?:whisper|speak softly|talk softly)|(?:speak|talk) (?:in a )?whisper|"
    r"don't wake|do not wake|someone is sleeping|someone's asleep|people are sleeping|"
    r"in a quiet room)\b",
    re.IGNORECASE,
)
_URGENT_CUES = re.compile(
    r"\b(?:urgent|emergency|life[- ]threatening|immediate danger|fire alarm|"
    r"evacuate now|call emergency services|seek immediate help)\b",
    re.IGNORECASE,
)
_NORMAL_CUES = re.compile(
    r"\b(?:normal voice|regular voice|usual voice|speak normally|talk normally|"
    r"stop whispering|no more whispering|don't whisper|do not whisper)\b",
    re.IGNORECASE,
)


def choose_kokoro_voice(user_prompt: str = "", response_text: str = "") -> str:
    """Return one voice ID; urgent output stays clear, otherwise auto-whisper only on clear cues."""
    mode = os.environ.get("JARVIS_KOKORO_VOICE_MODE", "auto").strip().lower()
    normal = os.environ.get("JARVIS_KOKORO_NORMAL_VOICE", "").strip()
    if not normal:
        legacy = os.environ.get("JARVIS_KOKORO_VOICE", "").strip()
        normal = legacy if legacy and legacy != "jarvis_whisper" else "am_eric"
    whisper = os.environ.get("JARVIS_KOKORO_WHISPER_VOICE", "jarvis_whisper").strip()

    if _URGENT_CUES.search(str(response_text or "")):
        return normal
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
