import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class KokoroIntegrationContractTests(unittest.TestCase):
    def test_persistent_worker_is_valid_python(self):
        source = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        ast.parse(source)

    def test_runtime_and_installer_are_english_only(self):
        client = (ROOT / "voice" / "kokoro_tts.py").read_text(encoding="utf-8")
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install_kokoro82m_termux.sh").read_text(encoding="utf-8")
        setup = (ROOT / "setup").read_text(encoding="utf-8")
        for filename in ("kokoro-v1.0.fp16.onnx", "voices-v1.0.bin"):
            self.assertIn(filename, client)
            self.assertIn(filename, installer)
            self.assertIn(filename, setup)
        for source in (client, worker, installer, setup):
            self.assertNotIn("kokoro-v1.1-zh", source)
            self.assertNotIn("voices-v1.1-zh", source)
        self.assertIn('if prefix not in ("a", "b")', worker)
        self.assertIn('if lang not in ("en-us", "en-gb")', worker)
        self.assertNotIn("ZHG2P", worker)
        self.assertNotIn("JAG2P", worker)
        self.assertIn('"voices_loaded": 1', worker)
        self.assertIn('ready.get("voices_loaded", 0) != 1', client)

    def test_worker_loads_one_model_and_one_speaker_embedding(self):
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        client = (ROOT / "voice" / "kokoro_tts.py").read_text(encoding="utf-8")
        self.assertIn("self.model_path = model_path", worker)
        self.assertIn("self.voices_path = voices_path", worker)
        self.assertIn("self.base_style = self._load_voice_style(self.selected_voice)", worker)
        self.assertIn("self.whisper_style = self.base_style", worker)
        self.assertIn("normal_style_preloaded", worker)
        self.assertIn("whisper_style_preloaded", client)
        self.assertIn("str(MODEL_V1), str(VOICES_V1), selected", client)

    def test_whisper_reuses_the_selected_english_speaker(self):
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        self.assertIn("def apply_lpc_whisper", worker)
        self.assertIn('if voice == WHISPER_VOICE:', worker)
        self.assertIn('return self.whisper_style, self.selected_lang, "whisper"', worker)
        self.assertIn("audio = apply_lpc_whisper(audio, breath_mix)", worker)

    def test_rtf_uses_wall_time_over_generated_audio_duration(self):
        manager = (ROOT / "voice" / "tts_manager.py").read_text(encoding="utf-8")
        self.assertIn('synth_metrics["seconds"] / synth_metrics["audio_seconds"]', manager)
        self.assertIn('"rtf_target": float(os.environ.get("JARVIS_KOKORO_RTF_TARGET", "0.2"))', manager)
        self.assertIn('"rtf_within_target"', manager)
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        self.assertIn('"rtf_target": float(os.environ.get("JARVIS_KOKORO_RTF_TARGET", "0.2"))', worker)
        self.assertIn('JARVIS_KOKORO_THREADS", "4"', worker)


if __name__ == "__main__":
    unittest.main()
