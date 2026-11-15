import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class KokoroIntegrationContractTests(unittest.TestCase):
    def test_persistent_worker_is_valid_python(self):
        source = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        ast.parse(source)

    def test_both_official_packs_and_all_157_voice_ids_are_integrated(self):
        client = (ROOT / "voice" / "kokoro_tts.py").read_text(encoding="utf-8")
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install_kokoro82m_termux.sh").read_text(encoding="utf-8")
        setup = (ROOT / "setup").read_text(encoding="utf-8")
        for filename in (
            "kokoro-v1.0.fp16.onnx", "voices-v1.0.bin",
            "kokoro-v1.1-zh.fp16.onnx", "voices-v1.1-zh.bin",
        ):
            self.assertIn(filename, client)
            self.assertIn(filename, installer)
        self.assertIn("EXPECTED_V1_VOICES = 54", worker)
        self.assertIn("EXPECTED_V11_VOICES = 103", worker)
        self.assertIn("len(self.voice_catalog) != 157", worker)
        self.assertIn("len(catalog) != 157", setup)
        self.assertIn("_show_kokoro_voice_catalog(catalog)", setup)
        self.assertIn("voices_loaded", client)

    def test_selected_model_only_and_selected_voice_is_cached_twice(self):
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        client = (ROOT / "voice" / "kokoro_tts.py").read_text(encoding="utf-8")
        self.assertIn("self.model_path = self.model_paths[self.model_family]", worker)
        self.assertIn("self.base_style = self._load_voice_style(selected_voice)", worker)
        self.assertIn("self.whisper_style = self.base_style.copy()", worker)
        self.assertIn("normal_style_preloaded", worker)
        self.assertIn("whisper_style_preloaded", client)

    def test_matching_voice_whisper_uses_lpc_dsp(self):
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        self.assertIn("def apply_lpc_whisper", worker)
        self.assertIn('if voice == WHISPER_VOICE:', worker)
        self.assertIn('return self.whisper_style, self.selected_lang, "whisper"', worker)
        self.assertIn("audio = apply_lpc_whisper(audio, breath_mix)", worker)
        self.assertNotIn("af_nicole", worker)
        self.assertNotIn("JARVIS_KOKORO_MALE_VOICE", worker)

    def test_chinese_and_japanese_use_language_specific_g2p(self):
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        self.assertIn("zh.ZHG2P(version=None)", worker)
        self.assertIn("ja.JAG2P()", worker)
        self.assertIn("misaki[", worker)

    def test_client_passes_the_selected_voice_and_both_asset_packs(self):
        client = (ROOT / "voice" / "kokoro_tts.py").read_text(encoding="utf-8")
        self.assertIn("str(MODEL_V1), str(VOICES_V1), str(MODEL_V11), str(VOICES_V11), selected", client)
        self.assertIn('ready.get("selected_voice") != selected', client)
        self.assertIn("def model_for_voice", client)


if __name__ == "__main__":
    unittest.main()
