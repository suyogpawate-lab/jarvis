"""Regression tests for prerecorded wake acknowledgements."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voice import wake_responses


class WakeResponseTests(unittest.TestCase):
    def test_missing_cache_fails_without_live_tts_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(wake_responses, "AUDIO_DIR", Path(temp)), \
                 patch("voice.tts_manager.tts.speak_blocking") as speak:
                with self.assertRaisesRegex(RuntimeError, "cache incomplete"):
                    wake_responses.play_random_wake_response()
                speak.assert_not_called()

    def test_complete_cache_plays_one_prerecorded_clip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(1, len(wake_responses.PHRASES) + 1):
                (root / f"wake_{index:02d}.mp3").write_bytes(b"clip")
            with patch.object(wake_responses, "AUDIO_DIR", root), \
                 patch.object(wake_responses, "play_recorded", return_value=True) as play:
                self.assertTrue(wake_responses.play_random_wake_response())
                play.assert_called_once()
                self.assertTrue(str(play.call_args.args[0]).endswith(".mp3"))


if __name__ == "__main__":
    unittest.main()
