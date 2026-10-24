"""Regression checks for the Termux:Float entry point."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TermuxFloatTests(unittest.TestCase):
    def test_launcher_sets_compact_mode_before_import(self):
        source = (ROOT / "jarvis_float.py").read_text(encoding="utf-8")
        self.assertLess(source.index('os.environ["JARVIS_FLOAT_MODE"] = "1"'), source.index("from jarvis import main"))

    def test_float_mode_is_environment_controlled(self):
        sys.path.insert(0, str(ROOT))
        import jarvis
        old = os.environ.get("JARVIS_FLOAT_MODE")
        try:
            os.environ["JARVIS_FLOAT_MODE"] = "1"
            self.assertTrue(jarvis.is_float_mode())
            os.environ["JARVIS_FLOAT_MODE"] = "0"
            self.assertFalse(jarvis.is_float_mode())
        finally:
            if old is None:
                os.environ.pop("JARVIS_FLOAT_MODE", None)
            else:
                os.environ["JARVIS_FLOAT_MODE"] = old


if __name__ == "__main__":
    unittest.main()
