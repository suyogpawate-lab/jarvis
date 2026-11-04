"""Random prerecorded voice acknowledgements for the JARVIS wake word."""
import random
from pathlib import Path

from voice.tts import play_recorded

PHRASES = (
    "Listening, sir.",
    "Yes, sir?",
    "Go ahead, sir.",
    "I'm listening, sir.",
    "Ready when you are, sir.",
    "At your service, sir.",
    "Online, sir.",
    "I'm here, sir.",
    "Proceed, sir.",
    "How can I help, sir?",
    "Yes? Go ahead.",
    "Listening now, sir.",
    "Ready, sir.",
    "I'm all ears, sir.",
    "Speak, sir.",
    "What do you need, sir?",
    "Standing by, sir.",
    "I'm listening.",
    "Go on, sir.",
    "Awaiting your command, sir.",
    "Ready for your instructions, sir.",
    "Here and listening, sir.",
    "At your command, sir.",
    "Yes. I'm listening.",
    "What's the task, sir?",
)

AUDIO_DIR = Path.home() / ".cache" / "jarvis" / "wake_responses"


def play_random_wake_response() -> bool:
    """Play a pre-generated acknowledgement only; never synthesize on the wake path."""
    available = [AUDIO_DIR / f"wake_{i:02d}.mp3" for i in range(1, len(PHRASES) + 1)]
    available = [path for path in available if path.is_file()]
    if len(available) != len(PHRASES):
        missing = len(PHRASES) - len(available)
        raise RuntimeError(
            f"Wake acknowledgement cache incomplete: {len(available)}/{len(PHRASES)} clips; "
            f"{missing} missing. Run the wake-response preparation command."
        )
    return play_recorded(str(random.choice(available)))
