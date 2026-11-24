"""Gapless KittenTTS synthesis helpers for the bundled ONNX worker."""
from __future__ import annotations

import numpy as np

# Kitten's style table supports 510 input positions. Two are reserved for
# start/end markers, leaving room for up to 508 phoneme symbols. Keep margin.
KITTEN_MAX_PHONEMES = 500


def configure_frontend(frontend_module) -> None:
    """Raise Kitten's conservative 350-phoneme split without exceeding style rows."""
    frontend_module.MAX_PHON = KITTEN_MAX_PHONEMES


def synthesize_gapless(model, text: str, voice: str, language: str, speed: float):
    """Return continuous PCM and chunk count, without Kitten's built-in 150 ms gaps."""
    chunks = [
        np.asarray(chunk, dtype=np.float32).reshape(-1)
        for chunk in model.generate_stream(
            text, voice=voice, language=language, speed=speed
        )
    ]
    chunks = [chunk for chunk in chunks if chunk.size]
    if not chunks:
        return np.zeros(0, dtype=np.float32), 0
    return np.concatenate(chunks), len(chunks)
