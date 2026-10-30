#!/usr/bin/env python3
"""Compatibility entry point for the JARVIS first-run setup script.

The canonical Groq + OmniRoute guided setup is kept in the extensionless setup file so it can
also be launched directly. This wrapper preserves the documented command:
    python setup.py [keys|gmail|whatsapp|contacts|apps|voice|wake|message_style]
"""
from pathlib import Path
import runpy

SETUP_SCRIPT = Path(__file__).resolve().with_name("setup")
if not SETUP_SCRIPT.is_file():
    raise SystemExit(f"JARVIS setup script is missing: {SETUP_SCRIPT}")
runpy.run_path(str(SETUP_SCRIPT), run_name="__main__")
