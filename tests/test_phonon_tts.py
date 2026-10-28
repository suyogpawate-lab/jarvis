import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from voice import phonon_tts


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.data


class PhononAdapterTests(unittest.TestCase):
    def make_model(self, root):
        model = root / "model"
        (model / "voices").mkdir(parents=True)
        for filename in ("config.json", "tokenizer.json", "model.q8.gguf"):
            (model / filename).write_text("fixture", encoding="utf-8")
        (model / "voices" / "edwin.safetensors").write_bytes(b"voice")
        return model

    def test_model_dir_rejects_incomplete_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"JARVIS_PHONON_DIR": temp}):
                with self.assertRaisesRegex(RuntimeError, "checkpoint is incomplete"):
                    phonon_tts.model_dir()

    def test_synth_posts_text_and_selected_voice_to_shared_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = self.make_model(root)
            wav = b"RIFF" + (40).to_bytes(4, "little") + b"WAVE" + b"\x00" * 40
            with patch.object(phonon_tts, "_load_env"), \
                 patch.object(phonon_tts, "model_dir", return_value=model), \
                 patch.object(phonon_tts, "_voice_and_quant", return_value=("edwin", "q8")), \
                 patch.object(phonon_tts, "ensure_server", return_value={"ready": True, "warmup_verified": True}) as ensure, \
                 patch.object(phonon_tts.urllib.request, "urlopen", return_value=FakeResponse(wav)) as urlopen, \
                 patch.dict(os.environ, {"PREFIX": temp}):
                output = phonon_tts.synth("  Hello   there.  ")
                self.assertTrue(output.is_file())
                self.assertEqual(output.read_bytes(), wav)
                ensure.assert_called_once()
                request = urlopen.call_args.args[0]
                self.assertEqual(request.full_url, phonon_tts.BASE_URL + "/speak")
                payload = json.loads(request.data.decode("utf-8"))
                self.assertEqual(payload, {"text": "Hello there.", "voice": "edwin"})
                output.unlink()

    def test_synth_rejects_empty_text_without_contacting_service(self):
        with patch.object(phonon_tts, "_load_env"), \
             patch.object(phonon_tts.urllib.request, "urlopen") as urlopen:
            with self.assertRaisesRegex(RuntimeError, "empty text"):
                phonon_tts.synth("  ")
            urlopen.assert_not_called()

    def test_warmup_requires_verified_service_health(self):
        payload = {
            "ready": True,
            "warmup_verified": True,
            "worker_pid": 1234,
            "worker_memory": {"VmRSS": "1000 kB"},
        }
        with patch.object(phonon_tts, "ensure_server", return_value=payload) as ensure:
            self.assertTrue(phonon_tts.warmup())
            ensure.assert_called_once()

    def test_service_configuration_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            model = self.make_model(Path(temp))
            with patch.object(phonon_tts, "model_dir", return_value=model), \
                 patch.object(phonon_tts, "_voice_and_quant", return_value=("edwin", "q8")):
                with self.assertRaisesRegex(RuntimeError, "different model configuration"):
                    phonon_tts._validate_service({
                        "model_dir": "/other/model",
                        "quant": "q8",
                        "ready": True,
                        "warmup_verified": True,
                    })

    def test_interrupt_increments_generation_and_notifies_service(self):
        before = phonon_tts._GENERATION
        with patch.object(phonon_tts.urllib.request, "urlopen", return_value=FakeResponse(b'{"ok":true}')) as urlopen:
            phonon_tts.interrupt()
        self.assertEqual(phonon_tts._GENERATION, before + 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, phonon_tts.BASE_URL + "/interrupt")


if __name__ == "__main__":
    unittest.main()
