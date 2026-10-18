from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"
RUNTIME_DIR = BASE_DIR / "runtime"

WAKE_WORD = "jarvis"

SAMPLE_RATE = 16000
CHANNELS = 1

# Seconds of audio processed per recognition cycle.
CHUNK_SECONDS = 2

# Silence threshold used by the audio input layer.
ENERGY_THRESHOLD = 350

# How long JARVIS remains in command-listening mode.
COMMAND_TIMEOUT = 8
