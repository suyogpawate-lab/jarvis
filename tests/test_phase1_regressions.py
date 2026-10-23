"""Phase 1 regression tests for deterministic routing helpers."""
import unittest

from android.app_aliases import (
    normalize_app_name,
    resolve_app_candidates,
    resolve_installed_packages,
)


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

    def test_ambiguous_explicit_name_does_not_guess(self):
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
