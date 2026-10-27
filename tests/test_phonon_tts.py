import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voice import phonon_tts


class PhononAdapterTests(unittest.TestCase):
    def test_model_dir_rejects_incomplete_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"JARVIS_PHONON_DIR": temp}):
                with self.assertRaisesRegex(RuntimeError, "checkpoint is incomplete"):
                    phonon_tts.model_dir()

    def test_synth_passes_text_before_output_option_and_returns_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / "model"
            (model / "voices").mkdir(parents=True)
            for filename in ("config.json", "tokenizer.json", "model.q8.gguf"):
                (model / filename).write_text("fixture", encoding="utf-8")
            (model / "voices" / "edwin.safetensors").write_bytes(b"voice")

            def fake_run(command, **kwargs):
                output = Path(command[command.index("-o") + 1])
                output.write_bytes(b"wav")
                self.assertEqual(command[command.index("-o") - 1], "Hello there.")
                self.assertEqual(command[command.index("--voice") + 1], "edwin")

                class Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""
                return Result()

            with patch.object(phonon_tts, "model_dir", return_value=model), \
                 patch.object(phonon_tts, "_exe", return_value="/fake/ptts"), \
                 patch.object(phonon_tts.subprocess, "run", side_effect=fake_run), \
                 patch.dict(os.environ, {
                     "PREFIX": temp,
                     "JARVIS_PHONON_VOICE": "edwin",
                     "JARVIS_PHONON_QUANT": "q8",
                 }):
                output = phonon_tts.synth("  Hello   there.  ")
                self.assertTrue(output.is_file())
                self.assertEqual(output.read_bytes(), b"wav")
                output.unlink()

    def test_empty_text_is_rejected_without_invoking_ptts(self):
        with patch.object(phonon_tts.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "empty text"):
                phonon_tts.synth("  ")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
