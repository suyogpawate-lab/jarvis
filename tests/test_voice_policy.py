import os
import unittest
from unittest.mock import patch

from voice.voice_policy import choose_kokoro_voice


class KokoroVoicePolicyTests(unittest.TestCase):
    def test_normal_voice_is_the_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(choose_kokoro_voice("Explain this equation."), "am_eric")

    def test_clear_whisper_requests_select_whisper(self):
        with patch.dict(os.environ, {"JARVIS_KOKORO_VOICE_MODE": "auto"}, clear=True):
            self.assertEqual(choose_kokoro_voice("Please whisper, someone is sleeping."), "jarvis_whisper")
            self.assertEqual(choose_kokoro_voice("Keep your voice down."), "jarvis_whisper")

    def test_normal_request_overrides_whisper_cue(self):
        with patch.dict(os.environ, {"JARVIS_KOKORO_VOICE_MODE": "auto"}, clear=True):
            self.assertEqual(choose_kokoro_voice("Use your normal voice, not a whisper."), "am_eric")

    def test_explicit_mode_overrides_context(self):
        with patch.dict(os.environ, {"JARVIS_KOKORO_VOICE_MODE": "normal"}, clear=True):
            self.assertEqual(choose_kokoro_voice("Please whisper."), "am_eric")
        with patch.dict(os.environ, {"JARVIS_KOKORO_VOICE_MODE": "whisper"}, clear=True):
            self.assertEqual(choose_kokoro_voice("Explain this normally."), "jarvis_whisper")

    def test_configurable_stock_voice_and_whisper_voice(self):
        env = {
            "JARVIS_KOKORO_VOICE_MODE": "auto",
            "JARVIS_KOKORO_NORMAL_VOICE": "bm_george",
            "JARVIS_KOKORO_WHISPER_VOICE": "jarvis_whisper",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(choose_kokoro_voice("Hello."), "bm_george")
            self.assertEqual(choose_kokoro_voice("Speak softly."), "jarvis_whisper")

    def test_legacy_whisper_default_does_not_force_whisper(self):
        with patch.dict(os.environ, {"JARVIS_KOKORO_VOICE": "jarvis_whisper"}, clear=True):
            self.assertEqual(choose_kokoro_voice("Hello."), "am_eric")


if __name__ == "__main__":
    unittest.main()
