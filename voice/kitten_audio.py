"""Punctuation-aware KittenTTS synthesis helpers for the bundled ONNX worker."""
from __future__ import annotations

import numpy as np

from voice.text_chunking import sentence_list

# Kitten's style table supports 510 input positions. Three are reserved for
# start/end markers, leaving room for up to 507 phoneme symbols. Keep margin.
KITTEN_MAX_PHONEMES = 500

# Silence is added at sentence boundaries, not between Kitten's internal
# phoneme chunks. A final punctuation pause is included in the WAV itself.
KITTEN_SENTENCE_PAUSE_MS = 550
KITTEN_TERMINAL_PAUSE_MS = 650


def configure_frontend(frontend_module, *, misaki_nltk: bool = False) -> None:
    """Set a safe phoneme window and optionally install lightweight Misaki G2P."""
    frontend_module.MAX_PHON = KITTEN_MAX_PHONEMES
    if misaki_nltk:
        from voice.kitten_misaki import MisakiNltkEnglishG2P
        frontend_module.EnglishG2P = MisakiNltkEnglishG2P


def synthesize_with_pauses(model, text: str, voice: str, language: str, speed: float):
    """Synthesize sentence-by-sentence and preserve audible punctuation pauses.

    Kitten's generate_stream() yields internal phoneme chunks. Those chunks
    remain contiguous for prosody and speed. Silence is inserted between
    sentences, and after a final sentence-ending punctuation mark so the
    playback endpoint does not swallow the full stop's natural pause.
    """
    sentences = sentence_list(text)
    if not sentences:
        return np.zeros(0, dtype=np.float32), 0

    sample_rate = int(getattr(model, "sample_rate", 24000))
    pieces: list[np.ndarray] = []
    chunk_count = 0

    for index, sentence in enumerate(sentences):
        sentence_chunks = [
            np.asarray(chunk, dtype=np.float32).reshape(-1)
            for chunk in model.generate_stream(
                sentence, voice=voice, language=language, speed=speed
            )
        ]
        sentence_chunks = [chunk for chunk in sentence_chunks if chunk.size]
        if not sentence_chunks:
            continue

        pieces.append(np.concatenate(sentence_chunks))
        chunk_count += len(sentence_chunks)

        if index < len(sentences) - 1:
            pause_ms = KITTEN_SENTENCE_PAUSE_MS
        elif sentence.rstrip().endswith((".", "?", "!")):
            pause_ms = KITTEN_TERMINAL_PAUSE_MS
        else:
            pause_ms = 0

        silence_samples = round(sample_rate * pause_ms / 1000.0)
        if silence_samples:
            pieces.append(np.zeros(silence_samples, dtype=np.float32))

    if not pieces:
        return np.zeros(0, dtype=np.float32), 0
    return np.concatenate(pieces), chunk_count


# Backwards-compatible name for any external imports. The implementation is
# now punctuation-aware rather than literally gapless.
synthesize_gapless = synthesize_with_pauses
