"""Persistent Phonon TTS worker.

The model is loaded once when this process starts. Requests are newline-delimited
JSON on stdin; each successful request writes one WAV and returns its path.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        import ptts
        from voice.phonon_tts import model_dir, _selected_voice

        directory = model_dir()
        voice = _selected_voice(directory)
        quant = os.environ.get("JARVIS_PHONON_QUANT", "q8").strip() or "q8"
        # TTS owns the Rust Synth instance for the lifetime of this worker.
        tts = ptts.TTS(
            model=str(directory),
            device="cpu",
            quant=quant,
            voice=voice,
            lang="en",
        )
        _emit({"ready": True, "sample_rate": int(tts.sample_rate), "voice": voice})
    except Exception as exc:
        _emit({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            if request.get("op") == "stop":
                _emit({"ok": True})
                break
            text = " ".join(str(request.get("text", "")).split())
            output = Path(str(request.get("output", "")))
            if not text or not str(output):
                raise ValueError("Request needs non-empty text and output path.")
            output.parent.mkdir(parents=True, exist_ok=True)
            tts.save(str(output), text, voice=voice)
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError("Phonon produced no WAV output.")
            _emit({"ok": True, "output": str(output)})
        except Exception as exc:
            _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
