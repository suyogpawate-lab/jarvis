import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class KokoroIntegrationContractTests(unittest.TestCase):
    def test_persistent_worker_is_valid_python(self):
        source = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        ast.parse(source)

    def test_fp16_assets_and_all_voice_archive_are_selected(self):
        client = (ROOT / "voice" / "kokoro_tts.py").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install_kokoro82m_termux.sh").read_text(encoding="utf-8")
        self.assertIn("kokoro-v1.0.fp16.onnx", client)
        self.assertIn("voices-v1.0.bin", client)
        self.assertIn("kokoro-v1.0.fp16.onnx", installer)
        self.assertIn("voices-v1.0.bin", installer)
        self.assertIn("voices_loaded", client)

    def test_supplied_whisper_modes_are_integrated(self):
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        manager = (ROOT / "voice" / "tts_manager.py").read_text(encoding="utf-8")
        self.assertIn('"formant"', worker)
        self.assertIn('"lpc"', worker)
        self.assertIn("apply_lpc_whisper", worker)
        self.assertIn("JARVIS_KOKORO_FORMANT_DEPTH", worker)
        self.assertIn("JARVIS_KOKORO_NICOLE_MIX", worker)
        self.assertIn("_warm_kokoro", manager)
        self.assertIn('"jarvis_whisper"', manager)

    def test_worker_keeps_model_resident_and_checks_54_voices(self):
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        client = (ROOT / "voice" / "kokoro_tts.py").read_text(encoding="utf-8")
        self.assertIn("InferenceSession", worker)
        self.assertIn("len(self.voice_names) < 54", worker)
        self.assertIn("subprocess.Popen", client)


if __name__ == "__main__":
    unittest.main()
