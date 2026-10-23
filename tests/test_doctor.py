"""Tests for read-only JARVIS diagnostics."""
import unittest
from unittest.mock import patch

from monitoring.doctor import collect_checks, format_report
from automation.command_dispatcher import CommandDispatcher


class DoctorTests(unittest.TestCase):
    def test_explicit_doctor_is_routed_before_ai(self):
        dispatcher = object.__new__(CommandDispatcher)
        dispatcher.execute_one = lambda command, argument: f"handled:{command}:{argument}"
        self.assertEqual(dispatcher.dispatch("/doctor"), "handled:doctor:")
        self.assertEqual(dispatcher.dispatch("/DOCTOR"), "handled:doctor:")

    def test_report_counts_failures_and_warnings(self):
        report = format_report([
            ("FAIL", "Project files", "missing: core/core.py"),
            ("WARN", "Ollama", "not reachable"),
            ("OK", "Python", "3.x"),
        ])
        self.assertIn("1 failure(s), 1 warning(s)", report)
        self.assertIn("core/core.py", report)

    def test_dotenv_provider_key_is_detected_without_exposing_value(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text("GROQ_API_KEY=secret-value\nOMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1\n", encoding="utf-8")
            with patch("monitoring.doctor.ROOT", root), \
                 patch.dict("os.environ", {}, clear=True), \
                 patch("monitoring.doctor._tcp_check", return_value=False), \
                 patch("monitoring.doctor.shutil.disk_usage", side_effect=OSError), \
                 patch("monitoring.doctor._memory_summary", return_value="unavailable"), \
                 patch("monitoring.doctor.shutil.which", return_value=None):
                report = format_report(collect_checks())
        self.assertIn("configured: Groq, OmniRoute", report)
        self.assertNotIn("secret-value", report)

    def test_empty_report(self):
        report = format_report([])
        self.assertIn("JARVIS /doctor", report)
        self.assertIn("0 failure(s), 0 warning(s)", report)

    def test_provider_keys_report_names_without_values(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "SECRET_DO_NOT_PRINT"}, clear=True), \
             patch("monitoring.doctor._tcp_check", return_value=False), \
             patch("monitoring.doctor.shutil.disk_usage", side_effect=OSError), \
             patch("monitoring.doctor._memory_summary", return_value="unavailable"), \
             patch("monitoring.doctor.shutil.which", return_value=None):
            report = format_report(collect_checks())
        self.assertIn("configured: Groq", report)
        self.assertNotIn("SECRET_DO_NOT_PRINT", report)

    def test_only_local_tcp_checks_are_attempted(self):
        with patch("monitoring.doctor._tcp_check", return_value=False) as tcp, \
             patch("monitoring.doctor.shutil.disk_usage", side_effect=OSError), \
             patch("monitoring.doctor._memory_summary", return_value="unavailable"), \
             patch("monitoring.doctor.shutil.which", return_value=None):
            collect_checks()
        self.assertEqual(tcp.call_count, 4)


if __name__ == "__main__":
    unittest.main()
