import unittest

from voice.tts_manager import _mpv_raw_audio_command


class TTSPlaybackContractTests(unittest.TestCase):
    def test_raw_audio_playback_ignores_user_mpv_config_and_sets_full_volume(self):
        command = _mpv_raw_audio_command(sample_width=2, sample_rate=24000, channels=1)
        self.assertEqual(command[0], "mpv")
        self.assertIn("--no-config", command)
        self.assertIn("--volume=100", command)
        self.assertIn("--demuxer=rawaudio", command)
        self.assertIn("--demuxer-rawaudio-format=s16le", command)
        self.assertIn("--demuxer-rawaudio-rate=24000", command)
        self.assertIn("--demuxer-rawaudio-channels=1", command)
        self.assertEqual(command[-1], "-")

    def test_unsupported_pcm_width_fails_before_starting_player(self):
        with self.assertRaisesRegex(RuntimeError, "Unsupported PCM sample width"):
            _mpv_raw_audio_command(sample_width=8, sample_rate=24000, channels=1)


if __name__ == "__main__":
    unittest.main()
