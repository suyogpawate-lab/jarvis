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

    def test_format_has_summary(self):
        self.assertIn("Summary:", format_doctor("invalid"))


if __name__ == "__main__":
    unittest.main()
