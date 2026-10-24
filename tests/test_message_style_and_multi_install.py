import os
import unittest
from unittest.mock import patch

from messaging.style_profile import message_style_config, style_instructions
from skills.multi_install import parse_github_url


class MessageStyleTests(unittest.TestCase):
    def test_invalid_style_falls_back_to_mirror(self):
        with patch.dict(os.environ, {"JARVIS_MESSAGE_STYLE": "wild"}, clear=False):
            self.assertEqual(message_style_config()["style"], "mirror")

    def test_genz_style_does_not_remove_formality_override(self):
        with patch.dict(os.environ, {"JARVIS_MESSAGE_STYLE": "genz"}, clear=False):
            prompt = style_instructions()
        self.assertIn("damnnn", prompt)
        self.assertIn("explicitly asks for formal", prompt)
        self.assertIn("serious/sensitive matter", prompt)

    def test_custom_language_and_examples(self):
        with patch.dict(os.environ, {
            "JARVIS_MESSAGE_STYLE": "casual",
            "JARVIS_MESSAGE_LANGUAGE": "Hinglish",
            "JARVIS_MESSAGE_EXAMPLES": "damnnn, gng",
        }, clear=False):
            prompt = style_instructions()
        self.assertIn("Hinglish", prompt)
        self.assertIn("damnnn, gng", prompt)

    def test_parse_repo_url(self):
        self.assertEqual(
            parse_github_url("https://github.com/acme/skills"),
            ("acme", "skills", None, ""),
        )

    def test_parse_folder_url(self):
        self.assertEqual(
            parse_github_url("https://github.com/acme/skills/tree/main/productivity"),
            ("acme", "skills", "main", "productivity"),
        )

    def test_reject_non_github_url(self):
        with self.assertRaises(ValueError):
            parse_github_url("https://example.com/acme/skills")


if __name__ == "__main__":
    unittest.main()
