#!/usr/bin/env python
"""
Test JARVIS voice components.

    python scripts/test_voice.py stt      # test speech-to-text only
    python scripts/test_voice.py wakeword # test wake-word detection
    python scripts/test_voice.py tts      # test text-to-speech
    python scripts/test_voice.py mic      # test microphone / audio input
    python scripts/test_voice.py all      # test all of the above
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_imports():
    """Check that all voice packages are installed."""
    print("Checking imports...")
    try:
        import numpy
        print("  ✓ numpy")
    except ImportError as e:
        print(f"  ✗ numpy: {e}")
        return False
    try:
        import sounddevice
        print("  ✓ sounddevice")
    except ImportError as e:
        print(f"  ✗ sounddevice: {e}")
        return False
    try:
        import openwakeword
        print("  ✓ openwakeword")
    except ImportError as e:
        print(f"  ✗ openwakeword: {e}")
        return False
    return True


def test_files():
    """Check that whisper.cpp and the model are present."""
    print("\nChecking required files...")
    whisper_bin = Path.home() / "whisper.cpp" / "build" / "bin" / "whisper-cli"
    model = ROOT / "voice" / "models" / "ggml-tiny.en.bin"

    if whisper_bin.exists():
        print(f"  ✓ whisper binary: {whisper_bin}")
    else:
        print(f"  ✗ whisper binary not found: {whisper_bin}")
        print("    Build it: bash install.sh --with-voice")
        return False

    if model.exists():
        size_mb = model.stat().st_size / 1e6
        print(f"  ✓ whisper model: {model} ({size_mb:.1f} MB)")
    else:
        print(f"  ✗ whisper model not found: {model}")
        print("    Download it: bash install.sh --with-voice")
        return False

    return True


def test_mic(duration=3):
    """Record a few seconds from the microphone."""
    print(f"\nTesting microphone (recording {duration}s)...")
    try:
        import sounddevice as sd
        import numpy as np

        rate = 16000
        frames = sd.rec(
            int(duration * rate),
            samplerate=rate,
            channels=1,
            dtype="int16",
        )
        print("  Recording... speak now!")
        sd.wait()
        rms = np.sqrt(np.mean(frames**2))
        print(f"  ✓ Recorded {duration}s (RMS: {rms:.0f})")
        return True
    except Exception as e:
        print(f"  ✗ Microphone test failed: {e}")
        return False


def test_stt():
    """Test speech-to-text with a 2-second recording."""
    print("\nTesting speech-to-text (recording 2s)...")
    try:
        import sounddevice as sd
        import numpy as np
        import subprocess
        from pathlib import Path

        # Record
        rate = 16000
        frames = sd.rec(
            int(2 * rate),
            samplerate=rate,
            channels=1,
            dtype="int16",
        )
        print("  Recording... say something!")
        sd.wait()

        # Save to a temp file in voice runtime directory
        runtime_dir = Path(__file__).resolve().parent.parent / "voice" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        wav_file = runtime_dir / "test_voice.wav"
        import wave

        with wave.open(str(wav_file), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(frames.tobytes())

        # Run whisper
        whisper_bin = Path.home() / "whisper.cpp" / "build" / "bin" / "whisper-cli"
        model = ROOT / "voice" / "models" / "ggml-tiny.en.bin"

        if not whisper_bin.exists():
            print(f"  ✗ whisper not found: {whisper_bin}")
            return False

        result = subprocess.run(
            [str(whisper_bin), "-m", str(model), "-f", str(wav_file), "-nt", "-np"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            print(f"  ✗ Whisper failed: {result.stderr}")
            return False

        # Parse output
        output = result.stdout
        text = None
        for line in output.split("\n"):
            if "[RESULT]" in line or line.strip() and not line.startswith("["):
                text = line.strip()

        if text:
            print(f"  ✓ STT result: '{text}'")
            return True
        else:
            print(f"  ✗ No speech detected. Output:\n{output}")
            return False

    except Exception as e:
        print(f"  ✗ STT test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_wakeword():
    """Test wake-word detection."""
    print("\nTesting wake-word detection...")
    try:
        from voice.wakeword import WakeWordDetector

        detector = WakeWordDetector("jarvis")

        tests = [
            ("jarvis", True),
            ("hey jarvis", True),
            ("JARVIS", True),
            ("jarvis can you help", True),
            ("please help me", False),
            ("what is that", False),
        ]

        all_pass = True
        for text, expected in tests:
            result = detector.detect(text)
            status = "✓" if result == expected else "✗"
            print(f"  {status} '{text}' -> {result} (expected {expected})")
            if result != expected:
                all_pass = False

        return all_pass
    except Exception as e:
        print(f"  ✗ Wake-word test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_tts():
    """Test text-to-speech."""
    print("\nTesting text-to-speech...")
    try:
        from voice.tts import speak

        print("  Speaking: 'Hello, this is a test.'")
        result = speak("Hello, this is a test.")
        if result:
            print("  ✓ TTS complete")
            return True
        else:
            print("  ✗ TTS playback failed")
            return False
    except Exception as e:
        print(f"  ✗ TTS test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="Test JARVIS voice components")
    parser.add_argument(
        "test",
        nargs="?",
        choices=["imports", "files", "mic", "stt", "wakeword", "tts", "all"],
        default="all",
        help="which test(s) to run",
    )
    args = parser.parse_args()

    results = {}

    if args.test in ("all", "imports"):
        results["imports"] = test_imports()

    if args.test in ("all", "files"):
        results["files"] = test_files()

    if args.test in ("all", "mic"):
        results["mic"] = test_mic()

    if args.test in ("all", "stt"):
        if results.get("files", True):
            results["stt"] = test_stt()

    if args.test in ("all", "wakeword"):
        results["wakeword"] = test_wakeword()

    if args.test in ("all", "tts"):
        results["tts"] = test_tts()

    print("\n" + "=" * 50)
    if all(results.values()):
        print("✓ All tests passed!")
        return 0
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"✗ {len(failed)} test(s) failed: {', '.join(failed)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
