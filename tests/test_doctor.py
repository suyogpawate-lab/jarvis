import unittest
from unittest.mock import patch

from monitoring.doctor import run_doctor, format_doctor


class DoctorTests(unittest.TestCase):
    def test_unknown_section_is_reported(self):
        self.assertEqual(run_doctor("invalid")[0]["status"], "error")

    def test_provider_checks_never_echo_secret(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-secret"}, clear=True):
            with patch("monitoring.doctor.socket.create_connection", side_effect=OSError("mocked")):
                rows = run_doctor("providers")
        groq = next(row for row in rows if row["name"] == "Groq")
        self.assertEqual(groq["status"], "configured")
        self.assertNotIn("test-secret", str(rows))


    def test_voice_checks_use_root_level_needle_and_whistle_assets(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            needle = root / "android-arm64" / "needle"
            needle.parent.mkdir()
            needle.touch()
            needle.chmod(0o700)
            (root / "whistle.cact").touch()
            with patch("monitoring.doctor.ROOT", root):
                rows = run_doctor("voice")
        statuses = {row["name"]: row["status"] for row in rows}
        self.assertEqual(statuses["Needle runner"], "ok")
        self.assertEqual(statuses["Whistle model"], "ok")


    def test_voice_doctor_flags_non_executable_needle(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            needle = root / "android-arm64" / "needle"
            needle.parent.mkdir()
            needle.touch()
            needle.chmod(0o600)
            (root / "whistle.cact").touch()
            with patch("monitoring.doctor.ROOT", root):
                rows = run_doctor("voice")
        statuses = {row["name"]: row["status"] for row in rows}
        self.assertEqual(statuses["Needle runner"], "unavailable")

    def test_format_has_summary(self):
        self.assertIn("Summary:", format_doctor("invalid"))


if __name__ == "__main__":
    unittest.main()
