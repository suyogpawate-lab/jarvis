import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voice.tts_manager import TTSManager


class FakePlayer:
    def __init__(self):
        self.return_code = 0

    def poll(self):
        return self.return_code

    def wait(self):
        return self.return_code

    def terminate(self):
        self.return_code = 0

    def kill(self):
        self.return_code = 0


class PhononPlaybackPipelineTests(unittest.TestCase):
    def test_phonon_buffers_one_complete_reply_before_starting_player(self):
        with tempfile.TemporaryDirectory() as temp:
            wav_path = Path(temp) / "complete-reply.wav"
            wav_path.write_bytes(b"RIFF-test-wave")
            player = FakePlayer()

            manager = object.__new__(TTSManager)
            manager._gen = 7
            manager._proc = None
            manager.last_pipeline_metrics = {}

            reply = (
                "This is the first sentence. "
                "This is the second sentence. "
                "This is the final sentence."
            )

            with patch("voice.phonon_tts.synth", return_value=wav_path) as synth, \
                 patch("voice.tts_manager.subprocess.Popen", return_value=player) as popen:
                self.assertTrue(manager._play_phonon_buffered(reply, 7))

            synth.assert_called_once_with(reply)
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0][-1], str(wav_path))
            self.assertFalse(wav_path.exists())
            self.assertEqual(manager.last_pipeline_metrics["mode"], "full_reply_buffer")
            self.assertEqual(manager.last_pipeline_metrics["queue_starvation_seconds"], 0.0)
            self.assertEqual(manager.last_pipeline_metrics["queue_starvation_events"], 0)

    def test_phonon_does_not_start_playback_if_interrupted_during_synthesis(self):
        with tempfile.TemporaryDirectory() as temp:
            wav_path = Path(temp) / "interrupted.wav"
            wav_path.write_bytes(b"RIFF-test-wave")

            manager = object.__new__(TTSManager)
            manager._gen = 8
            manager._proc = None
            manager.last_pipeline_metrics = {}

            def synth_and_interrupt(_text):
                manager._gen += 1
                return wav_path

            with patch("voice.phonon_tts.synth", side_effect=synth_and_interrupt), \
                 patch("voice.tts_manager.subprocess.Popen") as popen:
                self.assertTrue(manager._play_phonon_buffered("Stop this response.", 8))

            popen.assert_not_called()
            self.assertFalse(wav_path.exists())
            self.assertTrue(manager.last_pipeline_metrics["interrupted"])


if __name__ == "__main__":
    unittest.main()
