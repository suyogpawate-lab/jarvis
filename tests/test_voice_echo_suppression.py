import time
import unittest

from voice.listener import WhistleWakeListener


class FakeTTSManager:
    def __init__(self, spoken):
        now = time.monotonic()
        self._status = {
            "last_spoken_text": spoken,
            "last_started": now - 2.0,
            "last_finished": now - 1.0,
        }

    def status(self):
        return self._status


class VoiceEchoSuppressionTests(unittest.TestCase):
    def listener(self, spoken):
        listener = WhistleWakeListener.__new__(WhistleWakeListener)
        listener._tts_manager = FakeTTSManager(spoken)
        return listener

    def test_suppresses_near_verbatim_jarvis_response(self):
        listener = self.listener(
            "I'm functioning as expected—ready to help with whatever you need next, sir."
        )
        heard = "I'm functioning as expected right now with whatever you need next and so on."
        self.assertTrue(listener._is_recent_tts_echo(heard))

    def test_keeps_unrelated_user_request(self):
        listener = self.listener(
            "I'm here and ready to help, sir. Let me know what you'd like to do next."
        )
        self.assertFalse(listener._is_recent_tts_echo("Open Chrome and search for weather tomorrow."))

    def test_does_not_suppress_short_transcripts(self):
        listener = self.listener("Yes, sir. I can help with that.")
        self.assertFalse(listener._is_recent_tts_echo("Yes, sir."))


if __name__ == "__main__":
    unittest.main()
