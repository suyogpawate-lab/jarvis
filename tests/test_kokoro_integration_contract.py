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
        self.assertIn("kokoro-v1.0.int8.onnx", installer)
        self.assertIn("kokoro-v1.1-zh.int8.onnx", installer)
        self.assertIn("ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c", installer)
        self.assertIn("11751c087b4bbeed031e2b687b11dda698bd27ba0509472f960b57f835a999f7", installer)
        self.assertIn("kokoro-v1.1-zh.int8.onnx", client)

    def test_selected_model_only_and_selected_voice_is_cached_twice(self):
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        client = (ROOT / "voice" / "kokoro_tts.py").read_text(encoding="utf-8")
        self.assertIn("self.model_path = self.model_paths[self.model_family]", worker)
        self.assertIn("self.base_style = self._load_voice_style(selected_voice)", worker)
        self.assertIn("self.whisper_style = self.base_style.copy()", worker)
        self.assertIn("normal_style_preloaded", worker)
        self.assertIn("whisper_style_preloaded", client)

    def test_rtf_uses_wall_time_over_generated_audio_duration(self):
        manager = (ROOT / "voice" / "tts_manager.py").read_text(encoding="utf-8")
        self.assertIn('synth_metrics["seconds"] / synth_metrics["audio_seconds"]', manager)
        self.assertIn('"rtf_target": float(os.environ.get("JARVIS_KOKORO_RTF_TARGET", "0.2"))', manager)
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        self.assertIn('"rtf_target": float(os.environ.get("JARVIS_KOKORO_RTF_TARGET", "0.2"))', worker)
        self.assertIn('JARVIS_KOKORO_THREADS", "4"', worker)

    def test_successful_kokoro_playback_is_not_printed_to_terminal(self):
        manager = (ROOT / "voice" / "tts_manager.py").read_text(encoding="utf-8")
        self.assertNotIn("Playback completed via", manager)
        self.assertIn("[TTS ERROR]", manager)

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
        self.assertIn("self._g2p_available", worker)
        self.assertIn('["espeak-ng", "-q", "--ipa", "-v", lang, phrase]', worker)
        setup = (ROOT / "setup").read_text(encoding="utf-8")
        self.assertIn("sys.version_info >= (3, 14)", setup)

    def test_client_passes_the_selected_voice_and_both_asset_packs(self):
        client = (ROOT / "voice" / "kokoro_tts.py").read_text(encoding="utf-8")
        self.assertIn("str(MODEL_V1), str(VOICES_V1), str(MODEL_V11), str(VOICES_V11), selected", client)
        self.assertIn('ready.get("selected_voice") != selected', client)
        self.assertIn("def model_for_voice", client)
    def test_android_provider_policy_and_natural_token_boundaries_are_wired(self):
        worker = (ROOT / "scripts" / "kokoro_worker.py").read_text(encoding="utf-8")
        self.assertIn("select_onnx_providers(", worker)
        self.assertIn("bounded_token_runs(", worker)
        self.assertIn("whitespace_token=self.vocab.get(\" \")", worker)
        self.assertIn("model_file", worker)
        self.assertIn("audio={info['audio_seconds']}s", worker)


if __name__ == "__main__":
    unittest.main()
