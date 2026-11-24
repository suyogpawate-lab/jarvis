from types import SimpleNamespace

import numpy as np

from voice.kitten_audio import (
    KITTEN_MAX_PHONEMES,
    configure_frontend,
    synthesize_gapless,
)


class FakeKittenModel:
    sample_rate = 24000

    def generate_stream(self, text, voice, language, speed):
        assert text == "Hello. How are you?"
        assert voice == "otis"
        assert language == "en"
        assert speed == 0.88
        yield np.array([0.1, 0.2], dtype=np.float32)
        yield np.array([0.3, 0.4], dtype=np.float32)


def test_kitten_frontend_uses_safe_larger_phoneme_window():
    frontend = SimpleNamespace(MAX_PHON=350)
    configure_frontend(frontend)
    assert frontend.MAX_PHON == KITTEN_MAX_PHONEMES == 500


def test_kitten_chunks_are_joined_without_inserted_silence():
    audio, chunk_count = synthesize_gapless(
        FakeKittenModel(),
        "Hello. How are you?",
        voice="otis",
        language="en",
        speed=0.88,
    )
    np.testing.assert_array_equal(
        audio,
        np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32),
    )
    assert chunk_count == 2


def test_empty_kitten_stream_returns_empty_audio():
    class EmptyModel:
        def generate_stream(self, **kwargs):
            return iter(())

    audio, chunk_count = synthesize_gapless(
        EmptyModel(), "Hello.", voice="otis", language="en", speed=1.0
    )
    assert audio.size == 0
    assert chunk_count == 0
