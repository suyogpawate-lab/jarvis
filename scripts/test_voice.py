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
import os
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
    """Check that the Needle runner and Whistle weights are present."""
    print("\nChecking required files...")
    needle_bin = ROOT / "android-arm64" / "needle"
    model = ROOT / "whistle.cact"
    if needle_bin.is_file() and os.access(needle_bin, os.X_OK):
        print(f"  ✓ Needle runner: {needle_bin}")
    else:
        print(f"  ✗ executable Needle runner not found: {needle_bin}")
        print("    Install it: bash install.sh --with-voice")
        return False
    if model.is_file():
        size_mb = model.stat().st_size / 1e6
        print(f"  ✓ Whistle model: {model} ({size_mb:.1f} MB)")
    else:
        print(f"  ✗ Whistle model not found: {model}")
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
        rms = np.sqrt(np.mean(np.asarray(frames, dtype=np.float32) ** 2))
        print(f"  ✓ Recorded {duration}s (RMS: {rms:.0f})")
        return True
    except Exception as e:
        print(f"  ✗ Microphone test failed: {e}")
        return False


def test_stt():
    """Record two seconds and transcribe it with Whistle."""
    print("\nTesting Whistle speech-to-text (recording 2s)...")
    try:
        import sounddevice as sd
        import numpy as np
        import subprocess
        import json
        import wave

        rate = 16000
        frames = sd.rec(int(2 * rate), samplerate=rate, channels=1, dtype="int16")
        print("  Recording... say something!")
        sd.wait()
        runtime_dir = ROOT / "voice" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        wav_file = runtime_dir / "test_voice.wav"
        with wave.open(str(wav_file), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(frames.tobytes())

        needle_bin = ROOT / "android-arm64" / "needle"
        model = ROOT / "whistle.cact"
        if not needle_bin.is_file() or not model.is_file():
            print("  ✗ Needle/Whistle files missing. Run: bash install.sh --with-voice")
            return False
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = str(needle_bin.parent) + ":" + env.get("LD_LIBRARY_PATH", "")
        result = subprocess.run(
            [str(needle_bin), "--model", str(model), "--audio", str(wav_file)],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            print(f"  ✗ Whistle failed: {result.stderr}")
            return False
        try:
            payload = json.loads(result.stdout.strip())
            transcript = str(payload.get("text") or "").strip()
        except (json.JSONDecodeError, AttributeError):
            print(f"  ✗ Could not parse Whistle JSON output:\n{result.stdout}")
            return False
        if transcript:
            print(f"  ✓ Whistle STT result: '{transcript}'")
            return True
        print(f"  ✗ No speech detected. Output:\n{result.stdout}")
        return False
    except Exception as e:
        print(f"  ✗ STT test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_wakeword(duration=15):
    """Test the real acoustic Hey Jarvis model against live microphone frames."""
    print(f"\nTesting acoustic wake-word detection (up to {duration}s)...")
    try:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model
    except Exception as e:
        print(f"  ✗ Required wake-word imports failed: {type(e).__name__}: {e}")
        return False

    model = None
    for framework in ("onnx", "tflite"):
        try:
            model = Model(wakeword_models=["hey_jarvis"], inference_framework=framework)
            print(f"  ✓ Acoustic model loaded ({framework})")
            break
        except Exception as e:
            print(f"  - {framework} unavailable: {type(e).__name__}: {e}")
    if model is None:
        print("  ✗ Could not load the Hey Jarvis acoustic model.")
        print("    Check the openwakeword model assets and installed ONNX/TFLite runtime.")
        return False

    threshold = float(os.getenv("JARVIS_WAKE_THRESHOLD", "0.50"))
    print(f"  Say “Hey Jarvis” clearly within {duration} seconds (threshold {threshold:.2f}).")
    max_score = 0.0
    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype='int16', blocksize=1280) as stream:
            deadline = time.monotonic() + duration
            last_report = time.monotonic()
            while time.monotonic() < deadline:
                block, overflowed = stream.read(1280)
                frame = np.ascontiguousarray(np.asarray(block, dtype=np.int16).reshape(-1))
                if frame.size != 1280:
                    continue
                scores = model.predict(frame)
                score = max((float(v) for k, v in scores.items() if "hey_jarvis" in k.lower()), default=0.0)
                max_score = max(max_score, score)
                if score >= threshold:
                    print(f"  ✓ Hey Jarvis detected (score: {score:.3f})")
                    return True
                if time.monotonic() - last_report >= 2:
                    print(f"  Listening... best score so far: {max_score:.3f}")
                    last_report = time.monotonic()
        print(f"  ✗ No acoustic detection. Highest score: {max_score:.3f}; threshold: {threshold:.2f}")
        print("    If the score stays at 0.000, check microphone routing/permissions and model output keys.")
        return False
    except Exception as e:
        print(f"  ✗ Acoustic wake-word test failed: {type(e).__name__}: {e}")
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
