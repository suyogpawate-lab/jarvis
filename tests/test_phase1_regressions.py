"""Phase 1 regression tests for deterministic routing helpers."""
import ast
import unittest

from android.app_aliases import (
    normalize_app_name,
    resolve_app_candidates,
    resolve_installed_packages,
)


class Phase1IntegrationTests(unittest.TestCase):
    def test_hud_labels_voice_transcript(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        source = (root / "jarvis_ui.py").read_text(encoding="utf-8")
        self.assertIn("[VOICE TRANSCRIPT]", source)
        self.assertIn('_start_work(voice_prompt, source="voice")', source)

    def test_fast_agent_failures_are_logged(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        source = (root / "automation" / "command_dispatcher.py").read_text(encoding="utf-8")
        self.assertIn("[ROUTING WARN] Groq FastAgent failed", source)

    def test_android_launcher_does_not_require_package_list_or_monkey(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        source = (root / "jarvis.py").read_text(encoding="utf-8")
        start = source.index("def _launch_android_package(package):")
        end = source.index("\ndef handle_local_android_command", start)
        launcher = source[start:end]
        self.assertIn('"am", "start", "-n", resolved', launcher)
        self.assertIn('"am", "start", "-a", "android.intent.action.MAIN"', launcher)
        self.assertIn('shutil.which("monkey")', launcher)
        self.assertNotIn("installed = _android_package_ids()", launcher)

    def test_app_capture_targets_android_user_zero(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "capture_apps.py").read_text(encoding="utf-8")
        self.assertIn('"--user", "0"', source)

    def test_local_app_launch_has_known_alias_fallbacks(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        source = (root / "jarvis.py").read_text(encoding="utf-8")
        start = source.index("def handle_local_android_command(prompt):")
        end = source.index("# ==============================================================", start)
        handler = source[start:end]
        self.assertIn('"whatsapp": "com.whatsapp"', handler)
        self.assertIn('"chrome": "com.android.chrome"', handler)
        self.assertIn('candidates = candidates or (tuple(_resolve_app(app_text, explicit)) or None)', handler)

    def test_cli_prompt_stays_responsive_to_voice_commands(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        source = (root / "jarvis.py").read_text(encoding="utf-8")
        start = source.index("async def _read_prompt_async():")
        end = source.index("# MAIN (plain terminal CLI)", start)
        prompt_reader = source[start:end]
        self.assertIn("prompt_async", prompt_reader)
        self.assertIn("voice_command_queue.get_nowait()", prompt_reader)
        self.assertIn("asyncio.sleep(0.08)", prompt_reader)
        self.assertIn("patch_stdout()", prompt_reader)
        self.assertIn("_cli_pending_text", prompt_reader)
        self.assertNotIn('input("YOU  > ")', prompt_reader)

    def test_wake_phrase_preroll_is_not_sent_to_command_stt(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        source = (root / "voice" / "listener.py").read_text(encoding="utf-8")
        wake_start = source.index('if score >= self.WAKE_THRESHOLD:')
        wake_end = source.index('                        continue', source.index('preroll.clear()', wake_start))
        wake_block = source[wake_start:wake_end]
        self.assertIn("command_frames = []", wake_block)
        self.assertNotIn("command_frames = list(preroll)", wake_block)
        self.assertIn("preroll contains the wake phrase itself", wake_block)

    def test_voice_test_defaults_match_runtime_defaults(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        listener = (root / "voice" / "listener.py").read_text(encoding="utf-8")
        voice_test = (root / "scripts" / "test_voice.py").read_text(encoding="utf-8")
        self.assertIn('JARVIS_WAKE_THRESHOLD", "0.40"', listener)
        self.assertIn('JARVIS_WAKE_THRESHOLD", "0.40"', voice_test)
        self.assertIn('JARVIS_CONVERSATION_TIMEOUT", "20"', listener)

    def test_prompt_toolkit_is_a_core_dependency(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        requirements = (root / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("prompt_toolkit", requirements)



class AppAliasTests(unittest.TestCase):
    def setUp(self):
        self.apps = [
            {"name": "WhatsApp Messenger", "package": "com.whatsapp",
             "short": ["whatsapp", "wa"], "launchable": True, "system": False},
            {"name": "WhatsApp Business", "package": "com.whatsapp.w4b",
             "short": ["wab"], "launchable": True, "system": False},
            {"name": "Google Chrome", "package": "com.android.chrome",
             "short": ["chrome"], "launchable": True, "system": True},
        ]

    def test_normalization(self):
        self.assertEqual(normalize_app_name("  WhatsApp-Messenger! "), "whatsapp messenger")

    def test_exact_alias_resolves_package(self):
        self.assertEqual(resolve_app_candidates("wa", False, self.apps), ["com.whatsapp"])

    def test_explicit_partial_name_resolves_unique_app(self):
        self.assertEqual(resolve_app_candidates("whatsapp mes", True, self.apps), ["com.whatsapp"])

    def test_ambiguous_alias_does_not_guess(self):
        self.assertEqual(resolve_app_candidates("wa", False, [
            {"name": "Messenger", "package": "com.whatsapp", "short": ["wa"], "launchable": True},
            {"name": "Work Assistant", "package": "com.work.assistant", "short": ["wa"], "launchable": True},
        ]), [])

    def test_personal_nickname(self):
        self.assertEqual(resolve_app_candidates("wa", False, self.apps, {"wa": "WhatsApp Messenger"}), ["com.whatsapp"])

    def test_package_fallback_resolves_whatsapp(self):
        self.assertEqual(resolve_installed_packages("whatsapp", {"com.whatsapp", "com.android.chrome"}), ["com.whatsapp"])

    def test_package_fallback_prefers_exact_package_tail(self):
        self.assertEqual(resolve_installed_packages("whatsapp", {"com.whatsapp", "com.whatsapp.w4b"}), ["com.whatsapp"])


if __name__ == "__main__":
    unittest.main()
