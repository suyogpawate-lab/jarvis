"""
Offline speech-to-text interface.

The implementation is deliberately isolated.

Supported backend target:
    Vosk

No network request is performed by this module.
"""

import json
from pathlib import Path


class OfflineSTT:

    def __init__(self, model_path):
        self.model_path = Path(model_path)
        self.model = None
        self.recognizer = None

    def load(self):
        try:
            from vosk import Model, KaldiRecognizer
        except ImportError as exc:
            raise RuntimeError(
                "Vosk is not installed."
            ) from exc

        if not self.model_path.exists():
            raise RuntimeError(
                f"Offline STT model not found: {self.model_path}"
            )

        self.model = Model(str(self.model_path))

        self.recognizer = KaldiRecognizer(
            self.model,
            16000,
        )

    def accept_audio(self, pcm_bytes):
        if self.recognizer is None:
            raise RuntimeError(
                "STT engine has not been loaded."
            )

        accepted = self.recognizer.AcceptWaveform(
            pcm_bytes
        )

        if not accepted:
            return ""

        result = json.loads(
            self.recognizer.Result()
        )

        return result.get("text", "").strip()

    def partial(self):
        if self.recognizer is None:
            return ""

        result = json.loads(
            self.recognizer.PartialResult()
        )

        return result.get(
            "partial",
            "",
        ).strip()

    def final(self):
        if self.recognizer is None:
            return ""

        result = json.loads(
            self.recognizer.FinalResult()
        )

        return result.get(
            "text",
            "",
        ).strip()

    def reset(self):
        if self.model is None:
            return

        from vosk import KaldiRecognizer

        self.recognizer = KaldiRecognizer(
            self.model,
            16000,
        )
