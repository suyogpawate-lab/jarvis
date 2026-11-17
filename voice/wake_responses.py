"""Ten pre-rendered, voice-matched wake acknowledgements."""
import os
import random
from pathlib import Path

from jarvis_env import load_env

load_env()

from voice.tts import play_recorded

PHRASES = (
    "Yes, sir. I'm listening.",
    "At your service, sir.",
    "Go ahead. I'm ready.",
    "I'm here. What's the task?",
    "Ready when you are, sir.",
    "Online and listening.",
    "Of course, sir. Go ahead.",
    "Standing by for your instructions.",
    "Yes? How can I help?",
    "I'm listening. Proceed.",
)
FOLLOWUP_PHRASE = "Still there, sir? What would you like me to do next?"

BASE_AUDIO_DIR = Path.home() / ".cache" / "jarvis" / "wake_responses"


def selected_voice_key() -> str:
    provider = os.environ.get("JARVIS_TTS_PROVIDER", "edge").strip().lower() or "edge"
    voices = {
        "say": os.environ.get("JARVIS_SHERPA_VOICE", "alan"),
        "sherpa": os.environ.get("JARVIS_SHERPA_VOICE", "alan"),
        "kokoro": os.environ.get("JARVIS_KOKORO_NORMAL_VOICE", "am_eric"),
        "phonon": os.environ.get("JARVIS_PHONON_VOICE", "edwin"),
        "piper": os.environ.get("JARVIS_PIPER_VOICE", "alan"),
        "edge": os.environ.get("JARVIS_EDGE_VOICE", "en-GB-RyanNeural"),
    }
    voice = str(voices.get(provider, "default")).strip() or "default"
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in voice)
    return f"{provider}_{safe}"


def audio_dir() -> Path:
    return BASE_AUDIO_DIR / selected_voice_key()


def available_clips() -> list[Path]:
    directory = audio_dir()
    clips = []
    for index in range(1, len(PHRASES) + 1):
        for suffix in (".wav", ".mp3"):
            path = directory / f"wake_{index:02d}{suffix}"
            if path.is_file() and path.stat().st_size > 1024:
                clips.append(path)
                break
    return clips


def prepare_wake_response_player():
    """Resolve and validate all ten clips before microphone wake detection starts."""
    clips = tuple(available_clips())
    if len(clips) != len(PHRASES):
        raise RuntimeError(
            f"Wake acknowledgement cache incomplete for {selected_voice_key()}: "
            f"{len(clips)}/{len(PHRASES)} clips. Run: python setup.py voice"
        )

    def play() -> bool:
        return play_recorded(random.choice(clips), wait=False)

    return play


def followup_clip() -> Path | None:
    """Return the selected voice's pre-rendered conversation follow-up, if ready."""
    directory = audio_dir()
    for suffix in (".wav", ".mp3"):
        path = directory / f"followup{suffix}"
        if path.is_file() and path.stat().st_size > 1024:
            return path
    return None


def prepare_followup_response_player():
    """Preload the single follow-up clip before the microphone loop starts."""
    clip = followup_clip()
    if clip is None:
        raise RuntimeError(
            f"Follow-up audio is missing for {selected_voice_key()}. "
            "Run: python setup.py voice"
        )

    def play() -> bool:
        return play_recorded(clip, wait=False)

    return play


def play_random_wake_response() -> bool:
    """Compatibility helper; the listener should preload the player at startup."""
    return prepare_wake_response_player()
