"""Regression tests for Knowledge Hub upload filename handling."""
import unittest

from knowledge_hub.app import _safe_display_name


class SafeDisplayNameTests(unittest.TestCase):
    def test_hindi_filename_keeps_pdf_extension(self):
        self.assertEqual(_safe_display_name("रिपोर्ट.pdf", ""), "upload.pdf")

    def test_chinese_filename_keeps_pdf_extension(self):
        self.assertEqual(_safe_display_name("报告.pdf", ""), "upload.pdf")

    def test_ascii_stem_is_preserved(self):
        self.assertEqual(_safe_display_name("Research Notes.PDF", ""), "Research_Notes.pdf")

    def test_requested_name_uses_uploaded_extension(self):
        self.assertEqual(
            _safe_display_name("报告.pdf", "Quarterly Report.docx"),
            "Quarterly_Report.pdf",
        )

    def test_path_components_are_not_retained(self):
        self.assertEqual(_safe_display_name("../../报告.pdf", ""), "upload.pdf")

    def test_extensionless_name_remains_extensionless(self):
        self.assertEqual(_safe_display_name("报告", ""), "upload")


if __name__ == "__main__":
    unittest.main()
